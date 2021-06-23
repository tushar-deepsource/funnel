from __future__ import annotations

from copy import deepcopy
from textwrap import dedent
from typing import Dict, Iterable, Optional, Set, Type
import re

from sqlalchemy import DDL, event
from sqlalchemy.dialects.postgresql.base import (
    RESERVED_WORDS as POSTGRESQL_RESERVED_WORDS,
)

from flask import current_app

from furl import furl
from typing_extensions import TypedDict
from zxcvbn import zxcvbn
import pymdownx.superfences

from coaster.utils import (
    default_markdown_extension_configs,
    default_markdown_extensions,
    make_name,
)

from ..typing import T
from . import UrlType, db

__all__ = [
    'RESERVED_NAMES',
    'PASSWORD_MIN_LENGTH',
    'PASSWORD_MAX_LENGTH',
    'check_password_strength',
    'markdown_content_options',
    'add_to_class',
    'add_search_trigger',
    'visual_field_delimiter',
    'add_search_trigger',
    'valid_name',
    'valid_username',
    'quote_like',
    'ImgeeFurl',
    'ImgeeType',
]

RESERVED_NAMES: Set[str] = {
    '_baseframe',
    'about',
    'account',
    'admin',
    'api',
    'app',
    'apps',
    'auth',
    'blog',
    'boxoffice',
    'brand',
    'brands',
    'by',
    'client',
    'clients',
    'comments',
    'confirm',
    'contact',
    'contacts',
    'crew',
    'dashboard',
    'delete',
    'edit',
    'email',
    'emails',
    'embed',
    'event',
    'events',
    'ftp',
    'funnel',
    'funnels',
    'hacknight',
    'hacknights',
    'hgtv',
    'imap',
    'in',
    'json',
    'kharcha',
    'login',
    'logout',
    'members',
    'membership',
    'new',
    'news',
    'notification',
    'notifications',
    'org',
    'organisation',
    'organisations',
    'organization',
    'organizations',
    'orgs',
    'pop',
    'pop3',
    'profile',
    'profiles',
    'project',
    'projects',
    'proposal',
    'proposals',
    'register',
    'reset',
    'search',
    'siteadmin',
    'smtp',
    'static',
    'ticket',
    'tickets',
    'token',
    'tokens',
    'update',
    'updates',
    'venue',
    'venues',
    'video',
    'videos',
    'workshop',
    'workshops',
    'www',
}


class PasswordCheckType(TypedDict):
    """Typed dictionary for :func:`check_password_strength`."""

    is_weak: bool
    score: str
    warning: str
    suggestions: str


#: Minimum length for a password
PASSWORD_MIN_LENGTH = 8
#: Maximum length for a password
PASSWORD_MAX_LENGTH = 100
#: Strong passwords require a strength of at least 3 as per the zxcvbn
#: project documentation.
PASSWORD_MIN_SCORE = 3


def check_password_strength(
    password: str, user_inputs: Optional[Iterable] = None
) -> PasswordCheckType:
    result = zxcvbn(password, user_inputs)
    return {
        'is_weak': (
            len(password) < PASSWORD_MIN_LENGTH
            or result['score'] < PASSWORD_MIN_SCORE
            or bool(result['feedback']['warning'])
        ),
        'score': result['score'],
        'warning': result['feedback']['warning'],
        'suggestions': result['feedback']['suggestions'],
    }


# re.IGNORECASE needs re.ASCII because of a quirk in the characters it matches.
# https://docs.python.org/3/library/re.html#re.I
_username_valid_re = re.compile('^[a-z0-9]([a-z0-9-]*[a-z0-9])?$', re.I | re.A)
_name_valid_re = re.compile('^[a-z0-9]([a-z0-9-]*[a-z0-9])?$', re.A)


visual_field_delimiter = ' ¦ '

markdown_content_options: dict = {
    'extensions': deepcopy(default_markdown_extensions),
    'extension_configs': deepcopy(default_markdown_extension_configs),
}

markdown_content_options['extensions'].append('toc')  # Allow a table of contents
markdown_content_options['extension_configs']['toc'] = {
    # Make headings link to themselves, for easier sharing
    'anchorlink': True,
    # Add a `h:` prefix to the heading id, to avoid conflict with template identifiers
    'slugify': lambda value, separator: ('h:' + make_name(value, delim=separator)),
}

# Custom fences must use <pre><code> blocks and not <div> blocks, as linkify will mess
# with links inside <div> blocks
markdown_content_options['extension_configs'].setdefault('pymdownx.superfences', {})[
    'custom_fences'
] = [
    {
        'name': 'mermaid',
        'class': 'language-placeholder language-mermaid',
        'format': pymdownx.superfences.fence_code_format,
    },
    {
        'name': 'vega-lite',
        'class': 'language-placeholder language-vega-lite',
        'format': pymdownx.superfences.fence_code_format,
    },
]


def add_to_class(cls: Type, name: Optional[str] = None):
    """
    Add a new method to a class via a decorator. Takes an optional attribute name.

    Usage::

        @add_to_class(ExistingClass)
        def new_method(self, *args):
            pass

        @add_to_class(ExistingClass, 'new_property')
        @property
        def existing_class_new_property(self):
            pass
    """

    def decorator(attr):
        use_name = name or attr.__name__
        if use_name in cls.__dict__:
            raise AttributeError(f"{cls.__name__} already has attribute {use_name}")
        setattr(cls, use_name, attr)
        return attr

    return decorator


def reopen(cls: Type[T]):
    """
    Move the contents of the decorated class into an existing class and return it.

    Usage::

        @reopen(ExistingClass)
        class __ExistingClass:
            @property
            def new_property(self):
                pass

    This is equivalent to::

        def new_property(self):
            pass

        ExistingClass.new_property = property(new_property)

    This decorator is syntactic sugar to make class extension visually similar to class
    definition. It is not for monkey patching. It will refuse to overwrite existing
    attributes, and will reject a decorated class that contains base classes or a
    metaclass. If the existing class was processed by a metaclass, the new attributes
    added to it may not receive the same processing.

    This decorator is intended to aid legibility of bi-directional relationships in
    SQLAlchemy models, specifically where a basic backref is augmented with methods or
    properties that do more processing.
    """

    def decorator(temp_cls: Type) -> Type[T]:
        if temp_cls.__bases__ != (object,):
            raise TypeError("Reopened class cannot add base classes")
        if temp_cls.__class__ is not type:
            raise TypeError("Reopened class cannot add a metaclass")
        if {
            '__slots__',
            '__getattribute__',
            '__getattr__',
            '__setattr__',
            '__delattr__',
        }.intersection(set(temp_cls.__dict__.keys())):
            raise TypeError("Reopened class contains unsupported __attributes__")
        for attr, value in list(temp_cls.__dict__.items()):
            # Skip the standard Python attributes, process the rest
            if attr not in (
                '__dict__',
                '__doc__',
                '__module__',
                '__weakref__',
                '__annotations__',
            ):
                # Refuse to overwrite existing attributes
                if hasattr(cls, attr):
                    raise AttributeError(f"{cls.__name__} already has attribute {attr}")
                # All good? Copy the attribute over...
                setattr(cls, attr, value)
                # ...And remove it from the temporary class
                delattr(temp_cls, attr)
            # Merge typing annotations
            elif attr == '__annotations__':
                cls.__annotations__.update(value)
        # Return the original class. Leave the temporary class to the garbage collector
        return cls

    return decorator


def valid_username(candidate: str) -> bool:
    """
    Check if a username is valid.

    Letters, numbers and non-terminal hyphens only.
    """
    return not _username_valid_re.search(candidate) is None


def valid_name(candidate: str) -> bool:
    """
    Check if a name is valid.

    Lowercase letters, numbers and non-terminal hyphens only.
    """
    return not _name_valid_re.search(candidate) is None


def pgquote(identifier: str) -> str:
    """Add double quotes to the given identifier if required (PostgreSQL only)."""
    return (
        ('"%s"' % identifier) if identifier in POSTGRESQL_RESERVED_WORDS else identifier
    )


def quote_like(query):
    """
    Construct a LIKE query.

    Usage::

        column.like(quote_like(q))
    """
    # Escape the '%' and '_' wildcards in SQL LIKE clauses.
    # Some SQL dialects respond to '[' and ']', so remove them.
    return (
        query.replace('%', r'\%').replace('_', r'\_').replace('[', '').replace(']', '')
        + '%'
    )


def add_search_trigger(model: db.Model, column_name: str) -> Dict[str, str]:
    """
    Add a search trigger and returns SQL for use in migrations.

    Typical use::

        class MyModel(db.Model):
            ...
            search_vector = db.deferred(db.Column(
                TSVectorType(
                    'name', 'title', *indexed_columns,
                    weights={'name': 'A', 'title': 'B'},
                    regconfig='english'
                ),
                nullable=False,
            ))

            __table_args__ = (
                db.Index(
                    'ix_mymodel_search_vector',
                    'search_vector',
                    postgresql_using='gin'
                ),
            )

        add_search_trigger(MyModel, 'search_vector')

    To extract the SQL required in a migration:

        $ flask shell
        >>> print(models.add_search_trigger(models.MyModel, 'search_vector')['trigger'])

    Available keys: ``update``, ``trigger`` (for upgrades) and ``drop`` (for downgrades).

    :param model: Model class
    :param str column_name: Name of the tsvector column in the model
    """
    column = getattr(model, column_name)
    function_name = model.__tablename__ + '_' + column_name + '_update'
    trigger_name = model.__tablename__ + '_' + column_name + '_trigger'
    weights = column.type.options.get('weights', {})
    regconfig = column.type.options.get('regconfig', 'english')

    trigger_fields = []
    update_fields = []

    for col in column.type.columns:
        texpr = "to_tsvector('{regconfig}', COALESCE(NEW.{col}, ''))".format(
            regconfig=regconfig, col=pgquote(col)
        )
        uexpr = "to_tsvector('{regconfig}', COALESCE({col}, ''))".format(
            regconfig=regconfig, col=pgquote(col)
        )
        if col in weights:
            texpr = "setweight({expr}, '{weight}')".format(
                expr=texpr, weight=weights[col]
            )
            uexpr = "setweight({expr}, '{weight}')".format(
                expr=uexpr, weight=weights[col]
            )
        trigger_fields.append(texpr)
        update_fields.append(uexpr)

    trigger_expr = ' || '.join(trigger_fields)
    update_expr = ' || '.join(update_fields)

    trigger_function = dedent(
        '''
        CREATE FUNCTION {function_name}() RETURNS trigger AS $$
        BEGIN
            NEW.{column_name} := {trigger_expr};
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER {trigger_name} BEFORE INSERT OR UPDATE ON {table_name}
        FOR EACH ROW EXECUTE PROCEDURE {function_name}();
        '''.format(  # nosec
            function_name=pgquote(function_name),
            column_name=pgquote(column_name),
            trigger_expr=trigger_expr,
            trigger_name=pgquote(trigger_name),
            table_name=pgquote(model.__tablename__),
        )
    )

    update_statement = dedent(  # nosec
        '''  # noqa: S608
        UPDATE {table_name} SET {column_name} = {update_expr};
        '''.format(  # nosec
            table_name=pgquote(model.__tablename__),
            column_name=pgquote(column_name),
            update_expr=update_expr,
        )
    )

    drop_statement = dedent(
        '''
        DROP TRIGGER {trigger_name} ON {table_name};
        DROP FUNCTION {function_name}();
        '''.format(  # nosec
            trigger_name=pgquote(trigger_name),
            table_name=pgquote(model.__tablename__),
            function_name=pgquote(function_name),
        )
    )

    # FIXME: `DDL().execute_if` accepts a string dialect, but sqlalchemy-stubs
    # incorrectly declares the type as `Optional[Dialect]`
    # https://github.com/dropbox/sqlalchemy-stubs/issues/181

    event.listen(
        model.__table__,
        'after_create',
        DDL(trigger_function).execute_if(
            dialect='postgresql'  # type: ignore[arg-type]
        ),
    )

    event.listen(
        model.__table__,
        'before_drop',
        DDL(drop_statement).execute_if(dialect='postgresql'),  # type: ignore[arg-type]
    )

    return {
        'trigger': trigger_function,
        'update': update_statement,
        'drop': drop_statement,
    }


class ImgeeFurl(furl):
    def resize(self, width: int, height: Optional[int] = None) -> furl:
        """
        Return image url with `?size=WxH` suffixed to it.

        :param width: Width to resize the image to
        :param height: Height to resize the image to
        """
        if self.url:
            copy = self.copy()
            copy.args['size'] = f'{width}' if height is None else f'{width}x{height}'
            return copy
        return self


class ImgeeType(UrlType):
    url_parser = ImgeeFurl

    def process_bind_param(self, value, dialect):
        value = super().process_bind_param(value, dialect)
        if value:
            allowed_domains = current_app.config.get('IMAGE_URL_DOMAINS', [])
            allowed_schemes = current_app.config.get('IMAGE_URL_SCHEMES', [])
            parsed = self.url_parser(value)
            if allowed_domains and parsed.host not in allowed_domains:
                raise ValueError(
                    "Image must be hosted on {hosts}".format(
                        hosts=' or '.join(allowed_domains)
                    )
                )
            if allowed_schemes and parsed.scheme not in allowed_schemes:
                raise ValueError("Invalid scheme for the URL")
        return value
