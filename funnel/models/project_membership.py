# -*- coding: utf-8 -*-

from sqlalchemy.ext.declarative import declared_attr

from coaster.sqlalchemy import DynamicAssociationProxy, immutable

from . import db
from .membership import ImmutableMembershipMixin
from .project import Project

__all__ = ['ProjectCrewMembership']


class ProjectCrewMembership(ImmutableMembershipMixin, db.Model):
    """
    Users can be crew members of projects, with specified access rights.
    """

    __tablename__ = 'project_crew_membership'

    # List of is_role columns in this model
    __data_columns__ = ('is_editor', 'is_concierge', 'is_usher')

    __roles__ = {
        'all': {'read': {'user', 'is_editor', 'is_concierge', 'is_usher', 'project'}},
        'profile_admin': {'read': {'edit_url', 'delete_url'}},
        'project_editor': {'read': {'edit_url', 'delete_url'}},
    }

    project_id = immutable(
        db.Column(None, db.ForeignKey('project.id', ondelete='CASCADE'), nullable=False)
    )
    project = immutable(
        db.relationship(
            Project,
            backref=db.backref(
                'crew_memberships',
                lazy='dynamic',
                cascade='all, delete-orphan',
                passive_deletes=True,
            ),
        )
    )
    parent = immutable(db.synonym('project'))
    parent_id = immutable(db.synonym('project_id'))

    # Project crew roles (at least one must be True):

    #: Editors can edit all common and editorial details of an event
    is_editor = db.Column(db.Boolean, nullable=False, default=False)
    #: Concierges are responsible for logistics and have write access
    #: to common details plus read access to everything else. Unlike
    #: editors, they cannot edit the schedule
    is_concierge = db.Column(db.Boolean, nullable=False, default=False)
    #: Ushers help participants find their way around an event and have
    #: the ability to scan badges at the door
    is_usher = db.Column(db.Boolean, nullable=False, default=False)

    @declared_attr
    def __table_args__(cls):
        args = list(super(cls, cls).__table_args__)
        args.append(
            db.CheckConstraint(
                'is_editor IS TRUE OR is_concierge IS TRUE OR is_usher IS TRUE',
                name='project_crew_membership_has_role',
            )
        )
        return tuple(args)

    @property
    def edit_url(self):
        return self.url_for('edit', _external=True)

    @property
    def delete_url(self):
        return self.url_for('delete', _external=True)

    def offered_roles(self):
        """Roles offered by this membership record"""
        roles = set()
        if self.is_editor:
            roles.add('editor')
        if self.is_concierge:
            roles.add('concierge')
        if self.is_usher:
            roles.add('usher')
        return roles

    def roles_for(self, actor=None, anchors=()):
        roles = super(ProjectCrewMembership, self).roles_for(actor, anchors)
        if 'editor' in self.project.roles_for(actor, anchors):
            roles.add('project_editor')
        if 'admin' in self.project.profile.roles_for(actor, anchors):
            roles.add('profile_admin')
        return roles


# Project relationships: all crew, vs specific roles

Project.active_crew_memberships = db.relationship(
    ProjectCrewMembership,
    lazy='dynamic',
    primaryjoin=db.and_(
        ProjectCrewMembership.project_id == Project.id, ProjectCrewMembership.is_active
    ),
)

Project.active_editor_memberships = db.relationship(
    ProjectCrewMembership,
    lazy='dynamic',
    primaryjoin=db.and_(
        ProjectCrewMembership.project_id == Project.id,
        ProjectCrewMembership.is_active,
        ProjectCrewMembership.is_editor.is_(True),
    ),
)

Project.active_concierge_memberships = db.relationship(
    ProjectCrewMembership,
    lazy='dynamic',
    primaryjoin=db.and_(
        ProjectCrewMembership.project_id == Project.id,
        ProjectCrewMembership.is_active,
        ProjectCrewMembership.is_concierge.is_(True),
    ),
)

Project.active_usher_memberships = db.relationship(
    ProjectCrewMembership,
    lazy='dynamic',
    primaryjoin=db.and_(
        ProjectCrewMembership.project_id == Project.id,
        ProjectCrewMembership.is_active,
        ProjectCrewMembership.is_usher.is_(True),
    ),
)

Project.crew = DynamicAssociationProxy('active_crew_memberships', 'user')
Project.editors = DynamicAssociationProxy('active_editor_memberships', 'user')
Project.concierges = DynamicAssociationProxy('active_concierge_memberships', 'user')
Project.ushers = DynamicAssociationProxy('active_usher_memberships', 'user')
