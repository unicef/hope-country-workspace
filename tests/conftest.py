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
    os.environ.update(DJANGO_SETTINGS_MODULE="country_workspace.config.settings")
    os.environ.setdefault("MEDIA_ROOT", "/tmp/static/")
    os.environ.setdefault("STATIC_ROOT", "/tmp/media/")
    os.environ.setdefault("TEST_EMAIL_SENDER", "sender@example.com")
    os.environ.setdefault("TEST_EMAIL_RECIPIENT", "recipient@example.com")

    os.environ["MAILJET_API_KEY"] = "11"
    os.environ["MAILJET_SECRET_KEY"] = "11"
    os.environ["FILE_STORAGE_DEFAULT"] = (
        "django.core.files.storage.FileSystemStorage?location=/tmp/hde/storage/"
    )
    os.environ["FILE_STORAGE_STATIC"] = (
        "django.core.files.storage.FileSystemStorage?location=/tmp/hde/static/"
    )
    os.environ["FILE_STORAGE_MEDIA"] = (
        "django.core.files.storage.FileSystemStorage?location=/tmp/hde/storage/"
    )
    os.environ["FILE_STORAGE_HOPE"] = (
        "django.core.files.storage.FileSystemStorage?location=/tmp/hde/hope/"
    )
    os.environ["SOCIAL_AUTH_REDIRECT_IS_HTTPS"] = "0"
    os.environ["CELERY_TASK_ALWAYS_EAGER"] = "0"
    os.environ["SECURE_HSTS_PRELOAD"] = "0"
    os.environ["SECRET_KEY"] = "kugiugiuygiuygiuygiuhgiuhgiuhgiugiu"

    os.environ["GMAIL_USER"] = "11"
    os.environ["GMAIL_PASSWORD"] = "11"
    from django.conf import settings

    settings.ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
    settings.SIGNING_BACKEND = "testutils.signers.PlainSigner"
    settings.MEDIA_ROOT = "/tmp/media"
    settings.STATIC_ROOT = "/tmp/static"
    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
    os.makedirs(settings.STATIC_ROOT, exist_ok=True)

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
    from testutils.factories import CountryOfficeFactory

    return CountryOfficeFactory(name="Afghanistan")


@pytest.fixture
def reporters(db, afghanistan, user):
    from country_workspace.utils import get_or_create_defaults_group

    return get_or_create_defaults_group()
