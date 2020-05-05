# -*- coding: utf-8 -*-

from datetime import timedelta

from sqlalchemy import or_
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import defer
from sqlalchemy_utils import TimezoneType

from werkzeug.security import check_password_hash
from werkzeug.utils import cached_property

import bcrypt
import phonenumbers

from baseframe import __
from coaster.sqlalchemy import add_primary_relationship, failsafe_add, with_roles
from coaster.utils import (
    LabeledEnum,
    md5sum,
    newpin,
    newsecret,
    require_one_of,
    utcnow,
    valid_username,
)

from . import BaseMixin, TSVectorType, UuidMixin, db
from .helpers import add_search_trigger

__all__ = [
    'Organization',
    'AuthPasswordResetRequest',
    'Team',
    'USER_STATUS',
    'User',
    'UserEmail',
    'UserEmailClaim',
    'UserExternalId',
    'UserOldId',
    'UserPhone',
    'UserPhoneClaim',
]


class SharedProfileMixin:
    """
    Common methods between User and Organization to link to Profile
    """

    # The `name` property in User and Organization is not over here because
    # of what seems to be a SQLAlchemy bug: we can't override the expression
    # (both models need separate expressions) without triggering an inspection
    # of the `profile` relationship, which does not exist yet as the backrefs
    # are only fully setup when module loading is finished.
    # Doc: https://docs.sqlalchemy.org/en/latest/orm/extensions/hybrid.html#reusing-hybrid-properties-across-subclasses

    def is_valid_name(self, value):
        if not valid_username(value):
            return False
        existing = Profile.get(value)
        if existing and existing.owner != self:
            return False
        return True

    def validate_name_candidate(self, name):
        if name and name == self.name:
            return
        return Profile.validate_name_candidate(name)

    @property
    def is_public_profile(self):
        """Controls the visibility state of a public profile"""
        return self.profile is not None and self.profile.state.PUBLIC

    @is_public_profile.setter
    def is_public_profile(self, value):
        if not self.profile:
            raise ValueError("There is no profile")
        if value:
            if not self.profile.state.PUBLIC:
                self.profile.make_public()
        else:
            if self.profile.state.PUBLIC:
                self.profile.make_private()


class USER_STATUS(LabeledEnum):  # NOQA: N801
    #: Regular, active user
    ACTIVE = (0, 'active', __("Active"))
    #: Suspended account
    SUSPENDED = (1, 'suspended', __("Suspended"))
    #: Merged into another user
    MERGED = (2, 'merged', __("Merged"))
    #: Invited to make an account, doesn't have one yet
    INVITED = (3, 'invited', __("Invited"))


class User(SharedProfileMixin, UuidMixin, BaseMixin, db.Model):
    __tablename__ = 'user'
    __title_length__ = 80
    # XXX: Deprecated, still here for Baseframe compatibility
    userid = db.synonym('buid')
    #: The user's fullname
    fullname = with_roles(
        db.Column(db.Unicode(__title_length__), default='', nullable=False),
        read={'all'},
    )
    #: Alias for the user's fullname
    title = db.synonym('fullname')
    #: Bcrypt hash of the user's password
    pw_hash = db.Column(db.String(80), nullable=True)
    #: Timestamp for when the user's password last changed
    pw_set_at = db.Column(db.TIMESTAMP(timezone=True), nullable=True)
    #: Expiry date for the password (to prompt user to reset it)
    pw_expires_at = db.Column(db.TIMESTAMP(timezone=True), nullable=True)
    #: User's timezone
    timezone = with_roles(
        db.Column(TimezoneType(backend='pytz'), nullable=True), read={'owner'}
    )
    #: User's status (active, suspended, merged, etc)
    status = db.Column(db.SmallInteger, nullable=False, default=USER_STATUS.ACTIVE)
    #: User avatar (URL to browser-ready image)
    avatar = with_roles(db.Column(db.UnicodeText, nullable=True), read={'all'})

    #: Other user accounts that were merged into this user account
    oldusers = association_proxy('oldids', 'olduser')

    search_vector = db.deferred(
        db.Column(
            TSVectorType(
                'fullname',
                weights={'fullname': 'A'},
                regconfig='english',
                hltext=lambda: User.fullname,
            ),
            nullable=False,
        )
    )

    __table_args__ = (
        db.Index(
            'ix_user_fullname_lower',
            db.func.lower(fullname).label('fullname_lower'),
            postgresql_ops={'fullname_lower': 'varchar_pattern_ops'},
        ),
        db.Index('ix_user_search_vector', 'search_vector', postgresql_using='gin'),
    )

    _defercols = [
        defer('created_at'),
        defer('updated_at'),
        defer('pw_hash'),
        defer('pw_set_at'),
        defer('pw_expires_at'),
        defer('timezone'),
    ]

    def __init__(self, password=None, **kwargs):
        self.password = password
        super(User, self).__init__(**kwargs)

    @hybrid_property
    def name(self):
        if self.profile:
            return self.profile.name

    @name.setter
    def name(self, value):
        if not value:
            if self.profile is not None:
                raise ValueError("Name is required")
        else:
            if self.profile is not None:
                self.profile.name = value
            else:
                self.profile = Profile(name=value, user=self, uuid=self.uuid)

    @name.expression
    def name(cls):  # NOQA: N805
        return db.select([Profile.name]).where(Profile.user_id == cls.id).label('name')

    with_roles(name, read={'all'})
    username = name

    @property
    def is_active(self):
        return self.status == USER_STATUS.ACTIVE

    def merged_user(self):
        if self.status == USER_STATUS.MERGED:
            return UserOldId.get(self.uuid).user
        else:
            return self

    def _set_password(self, password):
        if password is None:
            self.pw_hash = None
        else:
            self.pw_hash = bcrypt.hashpw(
                password.encode('utf-8'), bcrypt.gensalt()
            ).decode('ascii')
        self.pw_set_at = db.func.utcnow()
        # Expire passwords after one year. TODO: make this configurable
        self.pw_expires_at = self.pw_set_at + timedelta(days=365)

    #: Write-only property (passwords cannot be read back in plain text)
    password = property(fset=_set_password)

    def password_has_expired(self):
        return (
            self.pw_hash is not None
            and self.pw_expires_at is not None
            and self.pw_expires_at <= utcnow()
        )

    def password_is(self, password):
        if self.pw_hash is None:
            return False

        if self.pw_hash.startswith('sha1$'):  # XXX: DEPRECATED
            return check_password_hash(self.pw_hash, password)
        else:
            return bcrypt.hashpw(
                password.encode('utf-8'), self.pw_hash.encode('utf-8')
            ) == self.pw_hash.encode('utf-8')

    def __repr__(self):
        return '<User {username} "{fullname}">'.format(
            username=self.username or self.buid, fullname=self.fullname
        )

    @with_roles(read={'all'})
    @property
    def pickername(self):
        if self.username:
            return '{fullname} (@{username})'.format(
                fullname=self.fullname, username=self.username
            )
        else:
            return self.fullname

    @with_roles(read={'all'})
    @property
    def initials(self):
        """
        Return up to two initials from the user's fullname, for use as avatar stand-in.
        """
        return ''.join(word[0] for word in self.fullname.split(maxsplit=1) if word)

    def add_email(self, email, primary=False, type=None, private=False):  # NOQA: A002
        useremail = UserEmail(user=self, email=email, type=type, private=private)
        useremail = failsafe_add(db.session, useremail, user=self, email=email)
        if primary:
            self.primary_email = useremail
        return useremail

    def del_email(self, email):
        useremail = UserEmail.query.filter_by(user=self, email=email).first()
        if useremail:
            db.session.delete(useremail)
        if self.primary_email in (useremail, None):
            db.session.flush()
            self.primary_email = UserEmail.query.filter_by(user=self).first()

    @with_roles(read={'owner'})
    @cached_property
    def email(self):
        """
        Returns primary email address for user.
        """
        # Look for a primary address
        useremail = self.primary_email
        if useremail:
            return useremail
        # No primary? Maybe there's one that's not set as primary?
        useremail = UserEmail.query.filter_by(user=self).first()
        if useremail:
            # XXX: Mark at primary. This may or may not be saved depending on
            # whether the request ended in a database commit.
            self.primary_email = useremail
            return useremail
        # This user has no email address. Return a blank string instead of None
        # to support the common use case, where the caller will use str(user.email)
        # to get the email address as a string.
        return ''

    @with_roles(read={'owner'})
    @cached_property
    def phone(self):
        """
        Returns primary phone number for user.
        """
        # Look for a primary address
        userphone = self.primary_phone
        if userphone:
            return userphone
        # No primary? Maybe there's one that's not set as primary?
        userphone = UserPhone.query.filter_by(user=self).first()
        if userphone:
            # XXX: Mark at primary. This may or may not be saved depending on
            # whether the request ended in a database commit.
            self.primary_phone = userphone
            return userphone
        # This user has no phone number. Return a blank string instead of None
        # to support the common use case, where the caller will use str(user.phone)
        # to get the phone number as a string.
        return ''

    def roles_for(self, actor, anchors=()):
        roles = super().roles_for(actor, anchors)
        if actor == self:
            # Owner because the user owns their own account
            roles.add('owner')
            # Admin because it's relevant in the Profile model
            roles.add('admin')
        return roles

    def organizations_as_owner_ids(self):
        """
        Return the database ids of the organizations this user is an owner of. This is
        used for database queries.
        """
        return [
            membership.organization_id
            for membership in self.active_organization_owner_memberships
        ]

    def is_profile_complete(self):
        """
        Return True if profile is complete (fullname, username and email are present), False
        otherwise.
        """
        return bool(self.fullname and self.username and self.email)

    @classmethod
    def get(cls, username=None, buid=None, userid=None, defercols=False):
        """
        Return a User with the given username or buid.

        :param str username: Username to lookup
        :param str buid: Buid to lookup
        :param bool defercols: Defer loading non-critical columns
        """
        require_one_of(username=username, buid=buid, userid=userid)

        # userid parameter is temporary for Flask-Lastuser compatibility
        if userid:
            buid = userid

        if username is not None:
            query = cls.query.join(Profile).filter(Profile.name == username)
        else:
            query = cls.query.filter_by(buid=buid)
        if defercols:
            query = query.options(*cls._defercols)
        user = query.one_or_none()
        if user and user.status == USER_STATUS.MERGED:
            user = user.merged_user()
        if user and user.is_active:
            return user

    @classmethod
    def all(  # NOQA: A003
        cls, buids=None, userids=None, usernames=None, defercols=False
    ):
        """
        Return all matching users.

        :param list buids: Buids to look up
        :param list userids: Alias for ``buids`` (deprecated)
        :param list usernames: Usernames to look up
        :param bool defercols: Defer loading non-critical columns
        """
        users = set()
        if userids and not buids:
            buids = userids
        if buids and usernames:
            query = cls.query.join(Profile).filter(
                or_(cls.buid.in_(buids), Profile.name.in_(usernames))
            )
        elif buids:
            query = cls.query.filter(cls.buid.in_(buids))
        elif usernames:
            query = cls.query.join(Profile).filter(Profile.name.in_(usernames))
        else:
            raise Exception

        if defercols:
            query = query.options(*cls._defercols)
        for user in query.all():
            user = user.merged_user()
            if user.is_active:
                users.add(user)
        return list(users)

    @classmethod
    def autocomplete(cls, query):
        """
        Return users whose names begin with the query, for autocomplete widgets.
        Looks up users by fullname, username, external ids and email addresses.

        :param str query: Letters to start matching with
        """
        # Escape the '%' and '_' wildcards in SQL LIKE clauses.
        # Some SQL dialects respond to '[' and ']', so remove them.
        query = (
            query.replace('%', r'\%')
            .replace('_', r'\_')
            .replace('[', '')
            .replace(']', '')
            + '%'
        )
        # Use User._username since 'username' is a hybrid property that checks for validity
        # before passing on to _username, the actual column name on the model.
        # We convert to lowercase and use the LIKE operator since ILIKE isn't standard
        # and doesn't use an index on PostgreSQL (there's a functional index defined below).
        if not query:
            return []
        users = (
            cls.query.join(Profile)
            .filter(
                cls.status == USER_STATUS.ACTIVE,
                or_(  # Match against buid (exact value only), fullname or username, case insensitive
                    cls.buid == query[:-1],
                    db.func.lower(cls.fullname).like(db.func.lower(query)),
                    db.func.lower(Profile.name).like(db.func.lower(query)),
                ),
            )
            .options(*cls._defercols)
            .limit(100)
            .all()
        )  # Limit to 100 results
        if query.startswith('@') and UserExternalId.__at_username_services__:
            # Add Twitter/GitHub accounts to the head of results
            users = (
                cls.query.filter(
                    cls.status == USER_STATUS.ACTIVE,
                    cls.id.in_(
                        db.session.query(UserExternalId.user_id)
                        .filter(
                            UserExternalId.service.in_(
                                UserExternalId.__at_username_services__
                            ),
                            db.func.lower(UserExternalId.username).like(
                                db.func.lower(query[1:])
                            ),
                        )
                        .subquery()
                    ),
                )
                .options(*cls._defercols)
                .limit(100)
                .all()
                + users
            )
        elif '@' in query:
            users = (
                cls.query.filter(
                    cls.status == USER_STATUS.ACTIVE,
                    cls.id.in_(
                        db.session.query(UserEmail.user_id)
                        .filter(UserEmail.user_id.isnot(None))
                        .filter(
                            db.func.lower(UserEmail.email).like(db.func.lower(query))
                        )
                        .subquery()
                    ),
                )
                .options(*cls._defercols)
                .limit(100)
                .all()
                + users
            )
        return users

    @classmethod
    def active_user_count(cls):
        return cls.query.filter_by(status=USER_STATUS.ACTIVE).count()

    #: FIXME: Temporary values for Baseframe compatibility
    def organization_links(self):
        return []


add_search_trigger(User, 'search_vector')


class UserOldId(UuidMixin, BaseMixin, db.Model):
    __tablename__ = 'user_oldid'
    __uuid_primary_key__ = True

    #: Old user account, if still present
    olduser = db.relationship(
        User,
        primaryjoin='foreign(UserOldId.id) == remote(User.uuid)',
        backref=db.backref('oldid', uselist=False),
    )
    #: User id of new user
    user_id = db.Column(None, db.ForeignKey('user.id'), nullable=False)
    #: New user account
    user = db.relationship(
        User,
        primaryjoin=user_id == User.id,
        backref=db.backref('oldids', cascade='all'),
    )

    def __repr__(self):
        return '<UserOldId {buid} of {user}>'.format(
            buid=self.buid, user=repr(self.user)[1:-1]
        )

    @classmethod
    def get(cls, uuid):
        return cls.query.filter_by(id=uuid).one_or_none()


# --- Organizations and teams -------------------------------------------------

team_membership = db.Table(
    'team_membership',
    db.Model.metadata,
    db.Column(
        'user_id', None, db.ForeignKey('user.id'), nullable=False, primary_key=True
    ),
    db.Column(
        'team_id', None, db.ForeignKey('team.id'), nullable=False, primary_key=True
    ),
    db.Column(
        'created_at',
        db.TIMESTAMP(timezone=True),
        nullable=False,
        default=db.func.utcnow(),
    ),
)


class Organization(SharedProfileMixin, UuidMixin, BaseMixin, db.Model):
    __tablename__ = 'organization'
    __title_length__ = 80
    title = with_roles(
        db.Column(db.Unicode(__title_length__), default='', nullable=False),
        read={'all'},
    )

    search_vector = db.deferred(
        db.Column(
            TSVectorType(
                'title',
                weights={'title': 'A'},
                regconfig='english',
                hltext=lambda: Organization.title,
            ),
            nullable=False,
        )
    )

    __table_args__ = (
        db.Index(
            'ix_organization_search_vector', 'search_vector', postgresql_using='gin'
        ),
    )

    _defercols = [defer('created_at'), defer('updated_at')]

    def __init__(self, owner, *args, **kwargs):
        super(Organization, self).__init__(*args, **kwargs)
        db.session.add(
            OrganizationMembership(
                organization=self, user=owner, granted_by=owner, is_owner=True
            )
        )

    @hybrid_property
    def name(self):
        if self.profile:
            return self.profile.name

    @name.setter
    def name(self, value):
        if not value:
            if self.profile is not None:
                raise ValueError("Name is required")
        else:
            if self.profile is not None:
                self.profile.name = value
            else:
                self.profile = Profile(name=value, organization=self, uuid=self.uuid)

    @name.expression
    def name(cls):  # NOQA: N805
        return (
            db.select([Profile.name])
            .where(Profile.organization_id == cls.id)
            .label('name')
        )

    with_roles(name, read={'all'})

    def __repr__(self):
        return '<Organization {name} "{title}">'.format(
            name=self.name or self.buid, title=self.title
        )

    @with_roles(read={'all'})
    @property
    def pickername(self):
        if self.name:
            return '{title} (@{name})'.format(title=self.title, name=self.name)
        else:
            return self.title

    def permissions(self, user, inherited=None):
        perms = super().permissions(user, inherited)
        if 'view' in perms:
            perms.remove('view')
        if 'edit' in perms:
            perms.remove('edit')
        if 'delete' in perms:
            perms.remove('delete')

        if user and user in self.admin_users:
            perms.add('view')
            perms.add('edit')
            perms.add('view-teams')
            perms.add('new-team')
        if user and user in self.owner_users:
            perms.add('delete')
        return perms

    @classmethod
    def get(cls, name=None, buid=None, defercols=False):
        """
        Return an Organization with matching name or buid. Note that ``name`` is the username, not the title.

        :param str name: Name of the organization
        :param str buid: Buid of the organization
        :param bool defercols: Defer loading non-critical columns
        """
        require_one_of(name=name, buid=buid)

        if name is not None:
            query = cls.query.join(Profile).filter(Profile.name == name)
        else:
            query = cls.query.filter_by(buid=buid)
        if defercols:
            query = query.options(*cls._defercols)
        return query.one_or_none()

    @classmethod
    def all(cls, buids=None, names=None, defercols=False):  # NOQA: A003
        orgs = []
        if buids:
            query = cls.query.filter(cls.buid.in_(buids))
            if defercols:
                query = query.options(*cls._defercols)
            orgs.extend(query.all())
        if names:
            query = cls.query.join(Profile).filter(Profile.name.in_(names))
            if defercols:
                query = query.options(*cls._defercols)
            orgs.extend(query.all())
        return orgs


add_search_trigger(Organization, 'search_vector')


class Team(UuidMixin, BaseMixin, db.Model):
    __tablename__ = 'team'
    __title_length__ = 250
    #: Displayed name
    title = db.Column(db.Unicode(__title_length__), nullable=False)
    #: Organization
    organization_id = db.Column(None, db.ForeignKey('organization.id'), nullable=False)
    organization = db.relationship(
        Organization,
        primaryjoin=organization_id == Organization.id,
        backref=db.backref('teams', order_by=title, cascade='all'),
    )
    users = db.relationship(
        User, secondary=team_membership, lazy='dynamic', backref='teams'
    )  # No cascades here! Cascades will delete users

    def __repr__(self):
        return '<Team {team} of {organization}>'.format(
            team=self.title, organization=repr(self.organization)[1:-1]
        )

    @property
    def pickername(self):
        return self.title

    def permissions(self, user, inherited=None):
        perms = super(Team, self).permissions(user, inherited)
        if user and user in self.organization.admin_users:
            perms.add('edit')
            perms.add('delete')
        return perms

    @classmethod
    def migrate_user(cls, olduser, newuser):
        for team in list(olduser.teams):
            if team not in newuser.teams:
                # FIXME: This creates new memberships, updating `created_at`.
                # Unfortunately, we can't work with model instances as in the other
                # `migrate_user` methods as team_membership is an unmapped table.
                newuser.teams.append(team)
            db.session.delete(team)
        return [cls.__table__.name, team_membership.name]

    @classmethod
    def get(cls, buid, with_parent=False):
        """
        Return a Team with matching buid.

        :param str buid: Buid of the team
        """
        if with_parent:
            query = cls.query.options(db.joinedload(cls.organization))
        else:
            query = cls.query
        return query.filter_by(buid=buid).one_or_none()


# -- User email/phone and misc


class UserEmail(BaseMixin, db.Model):
    __tablename__ = 'user_email'
    user_id = db.Column(None, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship(
        User,
        primaryjoin=user_id == User.id,
        backref=db.backref('emails', cascade='all'),
    )
    _email = db.Column('email', db.Unicode(254), unique=True, nullable=False)
    md5sum = db.Column(db.String(32), unique=True, nullable=False)
    domain = db.Column(db.Unicode(253), nullable=False, index=True)

    private = db.Column(db.Boolean, nullable=False, default=False)
    type = db.Column(db.Unicode(30), nullable=True)  # NOQA: A003

    __table_args__ = (
        db.Index(
            'ix_user_email_email_lower',
            db.func.lower(_email).label('email_lower'),
            unique=True,
            postgresql_ops={'email_lower': 'varchar_pattern_ops'},
        ),
    )

    def __init__(self, email, **kwargs):
        super(UserEmail, self).__init__(**kwargs)
        self._email = email.lower()
        self.md5sum = md5sum(self._email)
        self.domain = email.split('@')[-1]

    # XXX: Are hybrid_property and synonym both required?
    # Shouldn't one suffice?
    @hybrid_property
    def email(self):
        return self._email

    #: Make email immutable. There is no setter for email.
    email = db.synonym('_email', descriptor=email)

    def __repr__(self):
        return '<UserEmail {email} of {user}>'.format(
            email=self.email, user=repr(self.user)[1:-1]
        )

    def __str__(self):
        return self.email

    @property
    def primary(self):
        return self.user.primary_email == self

    @primary.setter
    def primary(self, value):
        if value:
            self.user.primary_email = self
        else:
            if self.user.primary_email == self:
                self.user.primary_email = None

    @classmethod
    def get(cls, email=None, md5sum=None):
        """
        Return a UserEmail with matching email or md5sum.

        :param str email: Email address to lookup
        :param str md5sum: md5sum of email address to lookup
        """
        require_one_of(email=email, md5sum=md5sum)

        if email:
            return cls.query.filter(cls.email.in_([email, email.lower()])).one_or_none()
        else:
            return cls.query.filter_by(md5sum=md5sum).one_or_none()

    @classmethod
    def get_for(cls, user, email=None, md5sum=None):
        """
        Return a UserEmail with matching md5sum if it belongs to the given user

        :param User user: User to lookup for
        :param str md5sum: md5sum of email address
        """
        require_one_of(email=email, md5sum=md5sum)
        if email:
            return cls.query.filter(
                cls.user == user, cls.email.in_([email, email.lower()])
            ).one_or_none()
        else:
            return cls.query.filter_by(user=user, md5sum=md5sum).one_or_none()

    @classmethod
    def migrate_user(cls, old_user, new_user):
        primary_email = old_user.primary_email
        for useremail in list(old_user.emails):
            useremail.user = new_user
        if new_user.primary_email is None:
            new_user.primary_email = primary_email
        old_user.primary_email = None
        return [cls.__table__.name, user_email_primary_table.name]


class UserEmailClaim(BaseMixin, db.Model):
    __tablename__ = 'user_email_claim'
    user_id = db.Column(None, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship(
        User,
        primaryjoin=user_id == User.id,
        backref=db.backref('emailclaims', cascade='all'),
    )
    _email = db.Column('email', db.Unicode(254), nullable=True, index=True)
    verification_code = db.Column(db.String(44), nullable=False, default=newsecret)
    md5sum = db.Column(db.String(32), nullable=False, index=True)
    domain = db.Column(db.Unicode(253), nullable=False, index=True)

    private = db.Column(db.Boolean, nullable=False, default=False)
    type = db.Column(db.Unicode(30), nullable=True)  # NOQA: A003

    __table_args__ = (db.UniqueConstraint('user_id', 'email'),)

    def __init__(self, email, **kwargs):
        super(UserEmailClaim, self).__init__(**kwargs)
        self.verification_code = newsecret()
        self._email = email.lower()
        self.md5sum = md5sum(self._email)
        self.domain = email.split('@')[-1]

    @hybrid_property
    def email(self):
        return self._email

    #: Make email immutable. There is no setter for email.
    email = db.synonym('_email', descriptor=email)

    def __repr__(self):
        return '<UserEmailClaim {email} of {user}>'.format(
            email=self.email, user=repr(self.user)[1:-1]
        )

    def __str__(self):
        return self.email

    def permissions(self, user, inherited=None):
        perms = super(UserEmailClaim, self).permissions(user, inherited)
        if user and user == self.user:
            perms.add('verify')
        return perms

    @classmethod
    def migrate_user(cls, old_user, new_user):
        emails = {claim.email for claim in new_user.emailclaims}
        for claim in list(old_user.emailclaims):
            if claim.email not in emails:
                claim.user = new_user
            else:
                # New user also made the same claim. Delete old user's claim
                db.session.delete(claim)

    @classmethod
    def get_for(cls, user, email=None, md5sum=None):
        """
        Return a UserEmailClaim with matching email address for the given user.

        :param User user: User who claimed this email address
        :param str email: Email address to lookup
        :param str md5sum: md5sum of email address to lookup
        """
        require_one_of(email=email, md5sum=md5sum)
        if email:
            return (
                cls.query.filter(UserEmailClaim.email.in_([email, email.lower()]))
                .filter_by(user=user)
                .one_or_none()
            )
        else:
            return cls.query.filter_by(md5sum=md5sum, user=user).one_or_none()

    @classmethod
    def get_by(cls, md5sum, verification_code):
        return cls.query.filter_by(
            md5sum=md5sum, verification_code=verification_code
        ).one_or_none()

    @classmethod
    def all(cls, email):  # NOQA: A003
        """
        Return all UserEmailClaim instances with matching email address.

        :param str email: Email address to lookup
        """
        return cls.query.filter(UserEmailClaim.email.in_([email, email.lower()]))


class UserPhone(BaseMixin, db.Model):
    __tablename__ = 'user_phone'
    user_id = db.Column(None, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship(
        User,
        primaryjoin=user_id == User.id,
        backref=db.backref('phones', cascade='all'),
    )
    _phone = db.Column('phone', db.UnicodeText, unique=True, nullable=False)
    gets_text = db.Column(db.Boolean, nullable=False, default=True)

    private = db.Column(db.Boolean, nullable=False, default=False)
    type = db.Column(db.Unicode(30), nullable=True)  # NOQA: A003

    def __init__(self, phone, **kwargs):
        super(UserPhone, self).__init__(**kwargs)
        self._phone = phone

    @hybrid_property
    def phone(self):
        return self._phone

    phone = db.synonym('_phone', descriptor=phone)

    def __repr__(self):
        return '<UserPhone {phone} of {user}>'.format(
            phone=self.phone, user=repr(self.user)[1:-1]
        )

    def __str__(self):
        return self.phone

    def parsed(self):
        return phonenumbers.parse(self._phone)

    def formatted(self):
        return phonenumbers.format_number(
            self.parsed(), phonenumbers.PhoneNumberFormat.INTERNATIONAL
        )

    @property
    def primary(self):
        return self.user.primary_phone == self

    @primary.setter
    def primary(self, value):
        if value:
            self.user.primary_phone = self
        else:
            if self.user.primary_phone == self:
                self.user.primary_phone = None

    @classmethod
    def get(cls, phone):
        """
        Return a UserPhone with matching phone number.

        :param str phone: Phone number to lookup (must be an exact match)
        """
        return cls.query.filter_by(phone=phone).one_or_none()

    @classmethod
    def get_for(cls, user, phone):
        """
        Return a UserPhone with matching phone number if it belongs to the given user

        :param User user: User to check against
        :param str phone: Phone number to lookup (must be an exact match)
        """
        return cls.query.filter_by(user=user, phone=phone).one_or_none()

    @classmethod
    def migrate_user(cls, old_user, new_user):
        primary_phone = old_user.primary_phone
        for userphone in list(old_user.phones):
            userphone.user = new_user
        if new_user.primary_phone is None:
            new_user.primary_phone = primary_phone
        old_user.primary_phone = None
        return [cls.__table__.name, user_phone_primary_table.name]


class UserPhoneClaim(BaseMixin, db.Model):
    __tablename__ = 'user_phone_claim'
    user_id = db.Column(None, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship(
        User,
        primaryjoin=user_id == User.id,
        backref=db.backref('phoneclaims', cascade='all'),
    )
    _phone = db.Column('phone', db.UnicodeText, nullable=False, index=True)
    gets_text = db.Column(db.Boolean, nullable=False, default=True)
    verification_code = db.Column(db.Unicode(4), nullable=False, default=newpin)
    verification_attempts = db.Column(db.Integer, nullable=False, default=0)

    private = db.Column(db.Boolean, nullable=False, default=False)
    type = db.Column(db.Unicode(30), nullable=True)  # NOQA: A003

    __table_args__ = (db.UniqueConstraint('user_id', 'phone'),)

    def __init__(self, phone, **kwargs):
        super(UserPhoneClaim, self).__init__(**kwargs)
        self.verification_code = newpin()
        self._phone = phone

    @hybrid_property
    def phone(self):
        return self._phone

    phone = db.synonym('_phone', descriptor=phone)

    def __repr__(self):
        return '<UserPhoneClaim {phone} of {user}>'.format(
            phone=self.phone, user=repr(self.user)[1:-1]
        )

    def __str__(self):
        return self.phone

    def parsed(self):
        return phonenumbers.parse(self._phone)

    def formatted(self):
        return phonenumbers.format_number(
            self.parsed(), phonenumbers.PhoneNumberFormat.INTERNATIONAL
        )

    @classmethod
    def migrate_user(cls, old_user, new_user):
        phones = {claim.email for claim in new_user.phoneclaims}
        for claim in list(old_user.phoneclaims):
            if claim.phone not in phones:
                claim.user = new_user
            else:
                # New user also made the same claim. Delete old user's claim
                db.session.delete(claim)

    @hybrid_property
    def verification_expired(self):
        return self.verification_attempts >= 3

    def permissions(self, user, inherited=None):
        perms = super(UserPhoneClaim, self).permissions(user, inherited)
        if user and user == self.user:
            perms.add('verify')
        return perms

    @classmethod
    def get_for(cls, user, phone):
        """
        Return a UserPhoneClaim with matching phone number for the given user.

        :param str phone: Phone number to lookup (must be an exact match)
        :param User user: User who claimed this phone number
        """
        return cls.query.filter_by(phone=phone, user=user).one_or_none()

    @classmethod
    def all(cls, phone):  # NOQA: A003
        """
        Return all UserPhoneClaim instances with matching phone number.

        :param str phone: Phone number to lookup (must be an exact match)
        """
        return cls.query.filter_by(phone=phone).all()

    @classmethod
    def delete_expired(cls):
        """Delete expired phone claims"""
        # Delete if:
        # 1. The claim is > 1 hour old
        # 2. Too many unsuccessful verification attempts
        cls.query.filter(
            db.or_(
                cls.updated_at < (utcnow() - timedelta(hours=1)),
                cls.verification_expired,
            )
        ).delete(synchronize_session=False)


class AuthPasswordResetRequest(BaseMixin, db.Model):
    __tablename__ = 'auth_password_reset_request'
    user_id = db.Column(None, db.ForeignKey('user.id'), nullable=False, index=True)
    user = db.relationship(User)
    reset_code = db.Column(db.String(44), nullable=False, default=newsecret)

    def __init__(self, **kwargs):
        super(AuthPasswordResetRequest, self).__init__(**kwargs)
        self.reset_code = newsecret()

    @classmethod
    def get(cls, user, reset_code):
        return cls.query.filter_by(user=user, reset_code=reset_code).first()


class UserExternalId(BaseMixin, db.Model):
    __tablename__ = 'user_externalid'
    __at_username_services__ = []
    user_id = db.Column(None, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship(
        User,
        primaryjoin=user_id == User.id,
        backref=db.backref('externalids', cascade='all'),
    )
    service = db.Column(db.UnicodeText, nullable=False)
    userid = db.Column(db.UnicodeText, nullable=False)  # Unique id (or obsolete OpenID)
    username = db.Column(db.UnicodeText, nullable=True)  # LinkedIn returns full URLs
    oauth_token = db.Column(db.UnicodeText, nullable=True)
    oauth_token_secret = db.Column(db.UnicodeText, nullable=True)
    oauth_token_type = db.Column(db.UnicodeText, nullable=True)

    last_used_at = db.Column(
        db.TIMESTAMP(timezone=True), default=db.func.utcnow(), nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint('service', 'userid'),
        db.Index(
            'ix_user_externalid_username_lower',
            db.func.lower(username).label('username_lower'),
            postgresql_ops={'username_lower': 'varchar_pattern_ops'},
        ),
    )

    def __repr__(self):
        return '<UserExternalId {service}:{username} of {user}>'.format(
            service=self.service, username=self.username, user=repr(self.user)[1:-1]
        )

    @classmethod
    def get(cls, service, userid=None, username=None):
        """
        Return a UserExternalId with the given service and userid or username.

        :param str service: Service to lookup
        :param str userid: Userid to lookup
        :param str username: Username to lookup (may be non-unique)

        Usernames are not guaranteed to be unique within a service. An example is with Google,
        where the userid is a directed OpenID URL, unique but subject to change if the Lastuser
        site URL changes. The username is the email address, which will be the same despite
        different userids.
        """
        param, value = require_one_of(True, userid=userid, username=username)
        return cls.query.filter_by(**{param: value, 'service': service}).one_or_none()

    def permissions(self, user, inherited=None):
        perms = super(UserExternalId, self).permissions(user, inherited)
        if user and user == self.user:
            perms.add('delete_extid')
        return perms


user_email_primary_table = add_primary_relationship(
    User, 'primary_email', UserEmail, 'user', 'user_id'
)
user_phone_primary_table = add_primary_relationship(
    User, 'primary_phone', UserPhone, 'user', 'user_id'
)

# Tail imports
from .profile import Profile  # isort:skip
from .organization_membership import OrganizationMembership  # isort:skip
