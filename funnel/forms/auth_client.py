from __future__ import annotations

from urllib.parse import urlparse

from baseframe import _, __
from coaster.utils import getbool
import baseframe.forms as forms

from ..models import (
    AuthClient,
    AuthClientCredential,
    AuthClientTeamPermissions,
    AuthClientUserPermissions,
    valid_name,
)
from .helpers import strip_filters

__all__ = [
    'AuthClientForm',
    'AuthClientCredentialForm',
    'AuthClientPermissionEditForm',
    'TeamPermissionAssignForm',
    'UserPermissionAssignForm',
]


@AuthClient.forms('main')
class AuthClientForm(forms.Form):
    """Register a new OAuth client application."""

    title = forms.StringField(
        __("Application title"),
        validators=[forms.validators.DataRequired()],
        filters=[forms.filters.strip()],
        description=__("The name of your application"),
    )
    description = forms.TextAreaField(
        __("Description"),
        validators=[forms.validators.DataRequired()],
        description=__("A description to help users recognize your application"),
    )
    client_owner = forms.RadioField(
        __("Owner"),
        validators=[forms.validators.DataRequired()],
        description=__(
            "User or organization that owns this application. Changing the owner"
            " will revoke all currently assigned permissions for this app"
        ),
    )
    confidential = forms.RadioField(
        __("Application type"),
        coerce=getbool,
        default=True,
        choices=[
            (
                True,
                __(
                    "Confidential (server-hosted app, capable of storing secret key securely)"
                ),
            ),
            (
                False,
                __(
                    "Public (native or in-browser app, not capable of storing secret key securely)"
                ),
            ),
        ],
    )
    website = forms.URLField(
        __("Application website"),
        validators=[forms.validators.DataRequired(), forms.validators.URL()],
        filters=strip_filters,
        description=__("Website where users may access this application"),
    )
    redirect_uris = forms.TextListField(
        __("Redirect URLs"),
        validators=[
            forms.validators.OptionalIf('confidential'),
            forms.ForEach([forms.URL()]),
        ],
        filters=[forms.filters.strip_each()],
        description=__(
            "OAuth2 Redirect URL. If your app is available on multiple hostnames,"
            " list each redirect URL on a separate line"
        ),
    )
    allow_any_login = forms.BooleanField(
        __("Allow anyone to login"),
        default=True,
        description=__(
            "If your application requires access to be restricted to specific users,"
            " uncheck this, and only users who have been assigned a permission to the"
            " app will be able to login"
        ),
    )

    def validate_client_owner(self, field):
        if field.data == self.edit_user.buid:
            self.user = self.edit_user
            self.organization = None
        else:
            orgs = [
                org
                for org in self.edit_user.organizations_as_owner
                if org.buid == field.data
            ]
            if len(orgs) != 1:
                raise forms.ValidationError(_("Invalid owner"))
            self.user = None
            self.organization = orgs[0]

    def _urls_match(self, url1, url2):
        p1 = urlparse(url1)
        p2 = urlparse(url2)
        return (
            (p1.netloc == p2.netloc)
            and (p1.scheme == p2.scheme)
            and (p1.username == p2.username)
            and (p1.password == p2.password)
        )

    def validate_redirect_uri(self, field):
        if self.confidential.data and not self._urls_match(
            self.website.data, field.data
        ):
            raise forms.ValidationError(
                _("The scheme, domain and port must match that of the website URL")
            )


@AuthClientCredential.forms('main')
class AuthClientCredentialForm(forms.Form):
    """Generate new client credentials."""

    title = forms.StringField(
        __("What’s this for?"),
        validators=[forms.validators.DataRequired(), forms.validators.Length(max=250)],
        filters=[forms.filters.strip()],
        description=__(
            "Add a description to help yourself remember why this was generated"
        ),
    )


def permission_validator(form, field):
    permlist = field.data.split()
    for perm in permlist:
        if not valid_name(perm):
            raise forms.ValidationError(
                _("Permission ‘{perm}’ is malformed").format(perm=perm)
            )
    permlist.sort()
    field.data = ' '.join(permlist)


@AuthClient.forms('permissions_user')
@AuthClientUserPermissions.forms('assign')
class UserPermissionAssignForm(forms.Form):
    """Assign permissions to a user."""

    user = forms.UserSelectField(
        __("User"),
        validators=[forms.validators.DataRequired()],
        description=__("Lookup a user by their username or email address"),
    )
    perms = forms.StringField(
        __("Permissions"),
        validators=[forms.validators.DataRequired(), permission_validator],
    )


@AuthClient.forms('permissions_team')
@AuthClientTeamPermissions.forms('assign')
class TeamPermissionAssignForm(forms.Form):
    """Assign permissions to a team."""

    team_id = forms.RadioField(
        __("Team"),
        validators=[forms.validators.DataRequired()],
        description=__("Select a team to assign permissions to"),
    )
    perms = forms.StringField(
        __("Permissions"),
        validators=[forms.validators.DataRequired(), permission_validator],
    )

    def validate_team_id(self, field):
        teams = [team for team in self.organization.teams if team.buid == field.data]
        if len(teams) != 1:
            raise forms.ValidationError(_("Unknown team"))
        self.team = teams[0]


@AuthClientUserPermissions.forms('edit')
@AuthClientTeamPermissions.forms('edit')
class AuthClientPermissionEditForm(forms.Form):
    """Edit a user or team's permissions."""

    perms = forms.StringField(__("Permissions"), validators=[permission_validator])
