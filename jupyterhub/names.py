"""names utils"""

# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.
import re
from functools import wraps

from sqlalchemy import func
from tornado.log import app_log

from . import orm, scopes


def get_default_names():
    """Returns:
    default names (list): default role definitions as dictionaries:
      {
        'name': role name,
        'description': role description,
        'scopes': list of scopes,
      }
    """
    default_names = [
        {
            'name': 'user',
            'description': 'Standard user privileges',
            'scopes': [
                'self',
            ],
        },
        {
            'name': 'admin',
            'description': 'Elevated privileges (can do anything)',
            'scopes': [
                'admin-ui',
                'admin:users',
                'admin:servers',
                'admin:services',
                'tokens',
                'admin:groups',
                'list:services',
                'read:services',
                'read:hub',
                'proxy',
                'shutdown',
                'access:services',
                'access:servers',
                'read:names',
                'read:metrics',
                'shares',
            ],
        },
        {
            'name': 'server',
            'description': 'Post activity only',
            'scopes': [
                'users:activity!user',
                'access:servers!server',
            ],
        },
        {
            'name': 'token',
            'description': 'Token with same permissions as its owner',
            'scopes': ['inherit'],
        },
    ]
    return default_names


def get_names_for(orm_object):
    """Get names for a given User/Group/etc.

    If User, take into account the user's groups names as well

    Arguments:
      orm_object: orm.User, orm.Service, orm.Group
          Any role-having entity

    Returns:
      names (list): list of orm.Role objects assigned to the object.
    """
    if not isinstance(orm_object, orm.Base):
        raise TypeError(f"Only orm objects allowed, got {orm_object}")

    names = []
    names.extend(orm_object.names)

    if isinstance(orm_object, orm.User):
        for group in orm_object.groups:
            names.extend(group.names)
    return names


def names_to_scopes(names):
    """Returns set of raw (not expanded) scopes for a collection of names"""
    raw_scopes = set()

    for role in names:
        raw_scopes.update(role.scopes)
    return raw_scopes


def names_to_expanded_scopes(names, owner):
    """Returns a set of fully expanded scopes for a specified role or list of names

    Arguments:
      names (list(orm.Role): orm.Role objects to expand
      owner (obj): orm.User or orm.Service which holds the role(s)
          Used for expanding filters and metascopes such as !user.

    Returns:
      expanded scopes (set): set of all expanded scopes for the role(s)
    """
    return scopes.expand_scopes(names_to_scopes(names), owner=owner)


_role_name_pattern = re.compile(r'^[a-z][a-z0-9\-_~\.]{1,253}[a-z0-9]$')


class RoleValueError(ValueError):
    pass


class InvalidNameError(ValueError):
    pass


def _validate_role_name(name):
    """Ensure a role has a valid name

    Raises InvalidNameError if role name is invalid
    """
    if not _role_name_pattern.match(name):
        raise InvalidNameError(
            f"Invalid role name: {name!r}."
            " Role names must:\n"
            " - be 3-255 characters\n"
            " - contain only lowercase ascii letters, numbers, and URL unreserved special characters '-.~_'\n"
            " - start with a letter\n"
            " - end with letter or number\n"
        )
    return True


def create_role(db, role_dict, *, commit=True, reset_to_defaults=True):
    """Adds a new role to database or modifies an existing one

    Raises ScopeNotFound if one of the scopes defined for the role does not exist.
    Raises KeyError when the 'name' key is missing.
    Raises RoleValueError when attempting to override the `admin` role.
    Raises InvalidRoleNameError if role name is invalid.

    Returns the role object.
    """
    default_names = get_default_names()

    if 'name' not in role_dict.keys():
        raise KeyError('Role definition must have a name')
    else:
        name = role_dict['name']
        _validate_role_name(name)
        role = orm.Role.find(db, name)

    description = role_dict.get('description')
    scopes = role_dict.get('scopes')

    if name == "admin":
        for _role in get_default_names():
            if _role["name"] == "admin":
                admin_spec = _role
                break
        for key in ["description", "scopes"]:
            if key in role_dict and role_dict[key] != admin_spec[key]:
                raise RoleValueError(
                    f"Cannot override admin role admin.{key} = {role_dict[key]}"
                )

    # check if the provided scopes exist
    if scopes:
        # avoid circular import
        from .scopes import _check_scopes_exist

        _check_scopes_exist(scopes, who_for=f"role {role_dict['name']}")
    else:
        app_log.warning('Role %s will have no scopes', name)

    if role is None:
        managed_by_auth = role_dict.get('managed_by_auth', False)
        role = orm.Role(
            name=name,
            description=description,
            scopes=scopes,
            managed_by_auth=managed_by_auth,
        )
        db.add(role)
        if role_dict not in default_names:
            app_log.info('Role %s added to database', name)
    else:
        for attr in ["description", "scopes"]:
            default_value = getattr(orm.Role, attr).default
            if default_value:
                default_value = default_value.arg

            new_value = role_dict.get(attr, default_value)
            old_value = getattr(role, attr)
            if new_value != old_value and (
                reset_to_defaults or new_value != default_value
            ):
                setattr(role, attr, new_value)
                app_log.info(
                    f'Role attribute {role.name}.{attr} has been changed',
                )
                app_log.debug(
                    f'Role attribute {role.name}.{attr} changed from %r to %r',
                    old_value,
                    new_value,
                )
    if commit:
        db.commit()
    return role


def delete_role(db, rolename):
    """Removes a role from database"""
    # default names are not removable
    default_names = get_default_names()
    if any(role['name'] == rolename for role in default_names):
        raise ValueError('Default role %r cannot be removed', rolename)

    role = orm.Role.find(db, rolename)
    if role:
        db.delete(role)
        db.commit()
        app_log.info('Role %s has been deleted', rolename)
    else:
        raise KeyError('Cannot remove role %r that does not exist', rolename)


def _existing_only(func):
    """Decorator for checking if names exist"""

    @wraps(func)
    def _check_existence(
        db, entity, role=None, *, managed=False, commit=True, rolename=None
    ):
        if isinstance(role, str):
            rolename = role
        if rolename is not None:
            # if given as a str, lookup role by name
            role = orm.Role.find(db, rolename)
        if role is None:
            raise ValueError(f"Role {rolename} does not exist")

        return func(db, entity, role, commit=commit, managed=managed)

    return _check_existence


@_existing_only
def grant_role(db, entity, role, managed=False, commit=True):
    """Adds a role for users, services, groups or tokens"""
    if isinstance(entity, orm.APIToken):
        entity_repr = entity
    else:
        entity_repr = entity.name

    if role not in entity.names:
        enitity_name = type(entity).__name__.lower()
        entity.names.append(role)
        if managed:
            association_class = orm._role_associations[enitity_name]
            association = (
                db.query(association_class)
                .filter(
                    (getattr(association_class, f'{enitity_name}_id') == entity.id)
                    & (association_class.role_id == role.id)
                )
                .one()
            )
            association.managed_by_auth = True
        app_log.info(
            'Adding role %s for %s: %s',
            role.name,
            type(entity).__name__,
            entity_repr,
        )
        if commit:
            db.commit()


@_existing_only
def strip_role(db, entity, role, managed=False, commit=True):
    """Removes a role for users, services, groups or tokens"""
    if isinstance(entity, orm.APIToken):
        entity_repr = entity
    else:
        entity_repr = entity.name
    if role in entity.names:
        entity.names.remove(role)
        if commit:
            db.commit()
        app_log.info(
            'Removing role %s for %s: %s',
            role.name,
            type(entity).__name__,
            entity_repr,
        )


def assign_default_names(db, entity):
    """Assigns default role(s) to an entity:

    tokens get 'token' role

    users and services get 'admin' role if they are admin (removed if they are not)

    users always get 'user' role
    """
    if isinstance(entity, orm.Group):
        return

    # users and services all have 'user' role by default
    # and optionally 'admin' as well

    kind = type(entity).__name__
    app_log.debug(f'Assigning default role to {kind} {entity.name}')
    if entity.admin:
        grant_role(db, entity=entity, rolename="admin")
    else:
        admin_role = orm.Role.find(db, 'admin')
        if admin_role in entity.names:
            strip_role(db, entity=entity, rolename="admin")
    if kind == "User":
        grant_role(db, entity=entity, rolename="user")


def update_names(db, entity, names):
    """Add names to an entity (token, user, etc.)

    Calls `grant_role` for each role.
    """
    for rolename in names:
        grant_role(db, entity=entity, rolename=rolename)


def check_for_default_names(db, bearer):
    """Checks that role bearers have at least one role (default if none).
    Groups can be without a role
    """
    Class = orm.get_class(bearer)
    if Class in {orm.Group, orm.Service}:
        pass
    else:
        for obj in (
            db.query(Class)
            .outerjoin(orm.Role, Class.names)
            .group_by(Class.id)
            .having(func.count(orm.Role.id) == 0)
        ):
            assign_default_names(db, obj)
    db.commit()


def mock_names(app, name, kind):
    """Loads and assigns default names for mocked objects"""
    Class = orm.get_class(kind)
    obj = Class.find(app.db, name=name)
    default_names = get_default_names()
    for role in default_names:
        create_role(app.db, role)
    app_log.info('Assigning default names to mocked %s: %s', kind[:-1], name)
    assign_default_names(db=app.db, entity=obj)
