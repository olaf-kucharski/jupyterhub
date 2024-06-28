"""FirstNames utils"""

# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.
import re
from functools import wraps

from sqlalchemy import func
from tornado.log import app_log

from . import orm


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

    if 'name' not in firstName_dict.keys():
        raise KeyError('FirstName definition must have a name')
    else:
        name = firstName_dict['name']
        _validate_firstName_name(name)
        firstName = orm.FirstName.find(db, name)

    if firstName is None:
        managed_by_auth = firstName_dict.get('managed_by_auth', False)
        firstName = orm.FirstName(
            name=name,
            managed_by_auth=managed_by_auth,
        )
        db.add(firstName)
        app_log.info('FirstName %s added to database', name)
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

def update_firstNames(db, entity, firstNames):
    """Add firstNames to an entity (token, user, etc.)

    Calls `grant_firstName` for each firstName.
    """
    for firstNamename in firstNames:
        grant_firstName(db, entity=entity, firstNamename=firstNamename)
