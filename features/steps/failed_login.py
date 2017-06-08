from flask import g, session
from behave import when, then, given
from mock import MagicMock
from lastuser_core.models import db, User
from lastuser_oauth.views.helpers import logout_internal
from lastuserapp import app


@given("we do not know that user")
def given_existing_user(context):
    context.test_user = dict(
        username='bobthehacker',
        password='bobthehacker'
    )


@when("the nonexisting user tries to log in")
def when_login_form_submit(context):
    context.test_user['form.id'] = "passwordlogin"
    with app.test_client() as c:
        c.post('/login', data=context.test_user, follow_redirects=True)
        context.user = g.user


@then("we do not log the user in")
def user_login(context):
    assert context.user is None
