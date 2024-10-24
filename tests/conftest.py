import os
import sys
from pathlib import Path

import pytest
import responses
import vcr
from vcr.record_mode import RecordMode

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
    os.environ["DJANGO_SETTINGS_MODULE"] = "country_workspace.config.settings"
    os.environ.setdefault("STATIC_URL", "/static/")
    os.environ.setdefault("MEDIA_ROOT", "/tmp/static/")
    os.environ.setdefault("STATIC_ROOT", "/tmp/media/")
    os.environ.setdefault("TEST_EMAIL_SENDER", "sender@example.com")
    os.environ.setdefault("TEST_EMAIL_RECIPIENT", "recipient@example.com")

    os.environ["MAILJET_API_KEY"] = "11"
    os.environ["MAILJET_SECRET_KEY"] = "11"
    os.environ["SOCIAL_AUTH_REDIRECT_IS_HTTPS"] = "0"
    os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
    os.environ["SECURE_HSTS_PRELOAD"] = "0"
    # os.environ["SECRET_KEY"] = "kugiugiuygiuygiuygiuhgiuhgiuhgiugiu"

    os.environ["LOGGING_LEVEL"] = "CRITICAL"
    import django
    from django.conf import settings

    settings.ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
    settings.SIGNING_BACKEND = "testutils.signers.PlainSigner"
    settings.SECRET_KEY = "kugiugiuygiuygiuygiuhgiuhgiuhgiugiu"
    settings.CSRF_TRUSTED_ORIGINS = [
        "http://testserver",
    ]
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.SOCIAL_AUTH_REDIRECT_IS_HTTPS = False
    django.setup()


@pytest.fixture(autouse=True)
def setup(db):
    from constance import config
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
    from country_workspace.models import SyncLog
    from country_workspace.versioning.management.manager import Manager

    Manager().force_apply()
    with vcr.VCR(record_mode=RecordMode.ONCE).use_cassette(Path(__file__).parent / "sync_lookups.yaml"):
        SyncLog.objects.refresh()
