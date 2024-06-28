"""FirstNames utils"""

# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.
import re
from functools import wraps

from sqlalchemy import func
from tornado.log import app_log

from . import orm, scopes


def get_firstNames_for(orm_object):
    """Get firstNames for a given User

    Arguments:
      orm_object: orm.User.

    Returns:
      firstName: list of orm.FirstName objects assigned to the object.
    """
    if not isinstance(orm_object, orm.Base):
        raise TypeError(f"Only orm objects allowed, got {orm_object}")

    firstNames = []
    firstNames.extend(orm_object.firstNames)
    return firstNames

# Doesn't apply since no names of groups
#     if isinstance(orm_object, orm.User):
#         for group in orm_object.groups:
#             firstNames.extend(group.firstNames)
#     return firstNames

# No scopes
# def roles_to_scopes(roles):
#     """Returns set of raw (not expanded) scopes for a collection of roles"""
#     raw_scopes = set()
#
#     for role in roles:
#         raw_scopes.update(role.scopes)
#     return raw_scopes
#
#
# def roles_to_expanded_scopes(roles, owner):
#     """Returns a set of fully expanded scopes for a specified role or list of roles
#
#     Arguments:
#       roles (list(orm.Role): orm.Role objects to expand
#       owner (obj): orm.User or orm.Service which holds the role(s)
#           Used for expanding filters and metascopes such as !user.
#
#     Returns:
#       expanded scopes (set): set of all expanded scopes for the role(s)
#     """
#     return scopes.expand_scopes(roles_to_scopes(roles), owner=owner)


_firstName_name_pattern = re.compile(r'^[a-zA-Z ][a-zA-Z0-9\-_~\. ]{1,253}[a-zA-Z0-9 ]$')


class FirstNameValueError(ValueError):
    pass


class InvalidNameError(ValueError):
    pass


def _validate_firstName_name(name):
    """Ensure a firstName has a valid name

    Raises InvalidNameError if firstName name is invalid
    """
    if not _firstName_name_pattern.match(name):
        raise InvalidNameError(
            f"Invalid firstName name: {name!r}."
            " FirstName names must:\n"
            " - be 3-255 characters\n"
            " - contain only ascii letters, numbers, space, and URL unreserved special characters '-.~_'\n"
            " - start with a letter\n"
            " - end with letter or number\n"
        )
    return True


def create_firstName(db, firstName_dict, *, commit=True, reset_to_defaults=True):
    """Adds a new firstName to database or modifies an existing one

    Raises KeyError when the 'name' key is missing.
    Raises InvalidFirstNameNameError if firstName name is invalid.

    Returns the firstName object.
    """
    # No default names
    # default_firstNames = get_default_firstNames()

    if 'name' not in firstName_dict.keys():
        raise KeyError('FirstName definition must have a name')
    else:
        name = firstName_dict['name']
        _validate_firstName_name(name)
        firstName = orm.FirstName.find(db, name)

    # No description, no scopes
    # description = role_dict.get('description')
    # scopes = role_dict.get('scopes')

    # No default names, no admin name
    # if name == "admin":
    #     for _firstName in get_default_firstNames():
    #         if _firstName["name"] == "admin":
    #             admin_spec = _firstName
    #             break
    #     for key in ["description", "scopes"]:
    #         if key in firstName_dict and firstName_dict[key] != admin_spec[key]:
    #             raise FirstNameValueError(
    #                 f"Cannot override admin firstName admin.{key} = {firstName_dict[key]}"
    #             )

    # no scopes
    # if scopes:
    #     # avoid circular import
    #     from .scopes import _check_scopes_exist
    #
    #     _check_scopes_exist(scopes, who_for=f"firstName {firstName_dict['name']}")
    # else:
    #     app_log.warning('FirstName %s will have no scopes', name)

    if firstName is None:
        managed_by_auth = firstName_dict.get('managed_by_auth', False)
        firstName = orm.FirstName(
            name=name,
            # No description nor scopes
            # description=description,
            # scopes=scopes,
            managed_by_auth=managed_by_auth,
        )
        db.add(firstName)
        # No default firstNames
        # if firstName_dict not in default_firstNames:
        app_log.info('FirstName %s added to database', name)
    # There are no attributes
    # else:
        # for attr in ["description", "scopes"]:
        #     default_value = getattr(orm.FirstName, attr).default
        #     if default_value:
        #         default_value = default_value.arg
        #
        #     new_value = firstName_dict.get(attr, default_value)
        #     old_value = getattr(firstName, attr)
        #     if new_value != old_value and (
        #         reset_to_defaults or new_value != default_value
        #     ):
        #         setattr(firstName, attr, new_value)
        #         app_log.info(
        #             f'FirstName attribute {firstName.name}.{attr} has been changed',
        #         )
        #         app_log.debug(
        #             f'FirstName attribute {firstName.name}.{attr} changed from %r to %r',
        #             old_value,
        #             new_value,
        #         )
    if commit:
        db.commit()
    return firstName


def delete_firstName(db, firstNamename):
    """Removes a firstName from database"""

    firstName = orm.FirstName.find(db, firstNamename)
    if firstName:
        db.delete(firstName)
        db.commit()
        app_log.info('FirstName %s has been deleted', firstNamename)
    else:
        raise KeyError('Cannot remove firstName %r that does not exist', firstNamename)


def _existing_only(func):
    """Decorator for checking if firstNames exist"""

    @wraps(func)
    def _check_existence(
        db, entity, firstName=None, *, managed=False, commit=True, firstNamename=None
    ):
        if isinstance(firstName, str):
            firstNamename = firstName
        if firstNamename is not None:
            # if given as a str, lookup firstName by name
            firstName = orm.FirstName.find(db, firstNamename)
        if firstName is None:
            raise ValueError(f"FirstName {firstNamename} does not exist")

        return func(db, entity, firstName, commit=commit, managed=managed)

    return _check_existence


@_existing_only
def grant_firstName(db, entity, firstName, managed=False, commit=True):
    """Adds a firstName for users"""
    if isinstance(entity, orm.APIToken):
        entity_repr = entity
    else:
        entity_repr = entity.name

    if firstName not in entity.firstNames:
        enitity_name = type(entity).__name__
        entity.firstNames.append(firstName)
        if managed:
            association_class = orm._firstName_associations[enitity_name]
            association = (
                db.query(association_class)
                .filter(
                    (getattr(association_class, f'{enitity_name}_id') == entity.id)
                    & (association_class.firstName_id == firstName.id)
                )
                .one()
            )
            association.managed_by_auth = True
        app_log.info(
            'Adding firstName %s for %s: %s',
            firstName.name,
            type(entity).__name__,
            entity_repr,
        )
        if commit:
            db.commit()


@_existing_only
def strip_firstName(db, entity, firstName, managed=False, commit=True):
    """Removes a firstName for users"""
    if isinstance(entity, orm.APIToken):
        entity_repr = entity
    else:
        entity_repr = entity.name
    if firstName in entity.firstNames:
        entity.firstNames.remove(firstName)
        if commit:
            db.commit()
        app_log.info(
            'Removing firstName %s for %s: %s',
            firstName.name,
            type(entity).__name__,
            entity_repr,
        )

# There are no default firstNames
# def assign_default_firstNames(db, entity):
#     """Assigns default firstName(s) to an entity:
#
#     tokens get 'token' firstName
#
#     users and services get 'admin' firstName if they are admin (removed if they are not)
#
#     users always get 'user' firstName
#     """
#     if isinstance(entity, orm.Group):
#         return
#
#     # users and services all have 'user' firstName by default
#     # and optionally 'admin' as well
#
#     kind = type(entity).__name__
#     app_log.debug(f'Assigning default firstName to {kind} {entity.name}')
#     if entity.admin:
#         grant_firstName(db, entity=entity, firstNamename="admin")
#     else:
#         admin_firstName = orm.FirstName.find(db, 'admin')
#         if admin_firstName in entity.firstNames:
#             strip_firstName(db, entity=entity, firstNamename="admin")
#     if kind == "User":
#         grant_firstName(db, entity=entity, firstNamename="user")


def update_firstNames(db, entity, firstNames):
    """Add firstNames to an entity (token, user, etc.)

    Calls `grant_firstName` for each firstName.
    """
    for firstNamename in firstNames:
        grant_firstName(db, entity=entity, firstNamename=firstNamename)

# There are no default firstNames
# def check_for_default_firstNames(db, bearer):
#     """Checks that firstName bearers have at least one firstName (default if none).
#     Groups can be without a firstName
#     """
#     Class = orm.get_class(bearer)
#     if Class in {orm.Group, orm.Service}:
#         pass
#     else:
#         for obj in (
#             db.query(Class)
#             .outerjoin(orm.FirstName, Class.firstNames)
#             .group_by(Class.id)
#             .having(func.count(orm.FirstName.id) == 0)
#         ):
#             assign_default_firstNames(db, obj)
#     db.commit()

# no default firstNames
# def mock_firstNames(app, name, kind):
#     """Loads and assigns default firstNames for mocked objects"""
#     Class = orm.get_class(kind)
#     obj = Class.find(app.db, name=name)
#     default_firstNames = get_default_firstNames()
#     for firstName in default_firstNames:
#         create_firstName(app.db, firstName)
#     app_log.info('Assigning default firstNames to mocked %s: %s', kind[:-1], name)
#     assign_default_firstNames(db=app.db, entity=obj)
