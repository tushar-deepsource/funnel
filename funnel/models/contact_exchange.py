# -*- coding: utf-8 -*-

from . import db, TimestampMixin, User

__all__ = ['ContactExchange']


class ContactExchange(TimestampMixin, db.Model):
    """
    Model to track who scanned whose badge, at which event.
    """
    __tablename__ = 'contact_exchange'
    user_id = db.Column(None, db.ForeignKey('user.id'), primary_key=True)
    user = db.relationship(User, backref=db.backref('contacts', cascade='all, delete-orphan'))
    proposal_space_id = db.Column(None, db.ForeignKey('proposal_space.id'), primary_key=True)
    participant_id = db.Column(None, db.ForeignKey('participant.id'), primary_key=True)
