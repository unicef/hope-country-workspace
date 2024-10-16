import os
import sys
from pathlib import Path

import django

import pytest
import responses
from constance import config

here = Path(__file__).parent
sys.path.insert(0, str(here / "../src"))
sys.path.insert(0, str(here / "extras"))


def pytest_addoption(parser):
    parser.addoption(
        "--selenium",
        action="store_true",
        dest="enable_selenium",
        default=False,
        help="enable selenium tests",
    )

    parser.addoption(
        "--show-browser",
        "-S",
        action="store_true",
        dest="show_browser",
        default=False,
        help="will not start browsers in headless mode",
    )


def pytest_configure(config):
    if not config.option.enable_selenium and ("selenium" not in getattr(config.option, "markexpr")):
        if config.option.markexpr:
            config.option.markexpr += " and not selenium"
        else:
            config.option.markexpr = "not selenium"
    os.environ.update(DJANGO_SETTINGS_MODULE="country_workspace.config.settings")
    os.environ.setdefault("STATIC_URL", "/static/")
    os.environ.setdefault("MEDIA_ROOT", "/tmp/static/")
    os.environ.setdefault("STATIC_ROOT", "/tmp/media/")
    os.environ.setdefault("TEST_EMAIL_SENDER", "sender@example.com")
    os.environ.setdefault("TEST_EMAIL_RECIPIENT", "recipient@example.com")

    os.environ["MAILJET_API_KEY"] = "11"
    os.environ["MAILJET_SECRET_KEY"] = "11"
    os.environ["SOCIAL_AUTH_REDIRECT_IS_HTTPS"] = "0"
    os.environ["CELERY_TASK_ALWAYS_EAGER"] = "0"
    os.environ["SECURE_HSTS_PRELOAD"] = "0"
    os.environ["SECRET_KEY"] = "kugiugiuygiuygiuygiuhgiuhgiuhgiugiu"

    os.environ["LOGGING_LEVEL"] = "CRITICAL"
    from django.conf import settings

    settings.ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
    settings.SIGNING_BACKEND = "testutils.signers.PlainSigner"
    django.setup()


@pytest.fixture(autouse=True)
def setup(db):
    from testutils.factories import GroupFactory

    GroupFactory(name=config.NEW_USER_DEFAULT_GROUP)


@pytest.fixture()
def mocked_responses():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture()
def user(db):
    from testutils.factories import UserFactory

    return UserFactory()


@pytest.fixture()
def afghanistan(db):
    from testutils.factories import OfficeFactory

    return OfficeFactory(name="Afghanistan")


@pytest.fixture
def reporters(db, afghanistan, user):
    from django.conf import settings
    from django.contrib.auth.models import Group

    from country_workspace.security.utils import setup_workspace_group

    setup_workspace_group()
    return Group.objects.get(name=settings.ANALYST_GROUP_NAME)


@pytest.fixture(scope="function")
def active_marks(request):

    # Collect all the marks for this node (test)
    current_node = request.node
    marks = []
    while current_node:
        marks += [mark.name for mark in current_node.iter_markers()]
        current_node = current_node.parent

    # Get the mark expression - what was passed to -m
    markExpr = request.config.option.markexpr

    # Compile the mark expression
    from _pytest.mark.expression import Expression

    compiledMarkExpr = Expression.compile(markExpr)

    # Return a sequence of markers that match
    return [mark for mark in marks if compiledMarkExpr.evaluate(lambda candidate: candidate == mark)]


@pytest.fixture()
def force_migrated_records(request, active_marks):
    from django.apps import apps

    from hope_flex_fields.apps import sync_content_types
    from hope_flex_fields.utils import create_default_fields

    from country_workspace.versioning.api import run_scripts
    from country_workspace.versioning.checkers import create_hope_core_fieldset, create_hope_field_definitions
    from country_workspace.versioning.synclog import create_default_synclog

    if request.config.option.enable_selenium or "selenium" in active_marks:
        # we need to recreate these records because with selenium they are not available
        create_default_fields(apps, None)
        sync_content_types(None)
    create_hope_field_definitions()
    create_hope_core_fieldset()
    create_default_synclog()
    run_scripts()
