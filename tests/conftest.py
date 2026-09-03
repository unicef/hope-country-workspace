import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import factory
import pytest
import responses
from django.core.files.base import ContentFile
from django.core.files.storage.base import Storage

if TYPE_CHECKING:
    from country_workspace.models import User

here = Path(__file__).parent
sys.path.insert(0, str(here / "../src"))
sys.path.insert(0, str(here / "extras"))


class MockStorage(Storage):
    def __init__(self):
        self._file_content = None

    def save(self, name, content, max_length=None):
        self._file_content = content.read() if hasattr(content, "read") else content
        return "mocked/path/to/file"

    def get_available_name(self, name, max_length=None):
        return "mocked/path/to/file"

    def open(self, name, mode="rb"):
        if self._file_content is not None:
            return ContentFile(self._file_content)
        return ContentFile(b"id,name\n1,Test")


@pytest.fixture
def mock_storage():
    return MockStorage()


@pytest.fixture(autouse=True)
def patch_asyncjob(mock_storage):
    from django.db import models

    from country_workspace.models.jobs import AsyncJob

    AsyncJob._meta.get_field("file").storage = mock_storage
    AsyncJob._meta.get_field("file").__class__ = models.FileField


def pytest_addoption(parser):
    parser.addoption(
        "--with-integration",
        action="store_true",
        dest="with_integration",
        default=False,
        help="Run integration tests in addition to unit tests",
    )
    parser.addoption(
        "--only-integration",
        action="store_true",
        dest="only_integration",
        default=False,
        help="Run only integration tests",
    )


def pytest_collection_modifyitems(config, items):
    with_integration = config.option.with_integration
    only_integration = config.option.only_integration
    skip_integration = pytest.mark.skip(reason="need --with-integration or --only-integration option to run")

    for item in items:
        if "integration" in item.keywords:
            if not (with_integration or only_integration):
                item.add_marker(skip_integration)
        elif only_integration:
            item.add_marker(pytest.mark.skip(reason="not an integration test"))


def pytest_configure(config):
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
    os.environ["CELERY_TASK_STORE_EAGER_RESULT"] = "1"
    os.environ["SECURE_HSTS_PRELOAD"] = "0"
    os.environ["FILE_STORAGE_DEFAULT"] = "django.core.files.storage.FileSystemStorage?location=./~tests/storage/"
    os.environ["FILE_STORAGE_MEDIA"] = "django.core.files.storage.FileSystemStorage?location=./~tests/storage/"
    os.environ["FILE_STORAGE_HOPE"] = "django.core.files.storage.FileSystemStorage?location=./~tests/storage/hope"
    os.environ["LOGGING_LEVEL"] = "CRITICAL"
    os.environ.setdefault("SECRET_KEY", "kugiugiuygiuygiuygiuhgiuhgiuhgiugiu")
    os.environ.setdefault("HOPE_API_TOKEN", "kugiugiuygiuygiuygiuhgiuhgiuhgiugiu")
    os.environ.setdefault("AURORA_API_TOKEN", "aurora_token")

    import django
    from django.conf import settings

    settings.ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
    settings.SIGNING_BACKEND = "testutils.signers.PlainSigner"
    settings.CSRF_TRUSTED_ORIGINS = ["http://testserver"]
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_STORE_EAGER_RESULT = True
    settings.SOCIAL_AUTH_REDIRECT_IS_HTTPS = False
    settings.STREAMING = {
        "BROKER_URL": "console://",
        "CLIENT_NAME": "country-workspace-test",
        "MANAGER_CLASS": "streaming.manager.ChangeManager",
        "LISTEN_CALLBACK": "country_workspace.stream.callbacks.handle_event",
        "QUEUES": {
            "ocr_results": {"binding_keys": ["hcw.ocr.result"]},
        },
    }
    django.setup()
    from country_workspace.cache.manager import cache_manager

    cache_manager.active = False


@pytest.fixture(autouse=True)
def setup(db, worker_id, settings):
    from constance import config
    from testutils.factories import GroupFactory

    if worker_id != "master":
        from country_workspace.cache.manager import cache_manager

        cache_manager.prefix = f"cache{worker_id}"
    GroupFactory(name=config.NEW_USER_DEFAULT_GROUP)


@pytest.fixture
def mocked_responses():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture
def user(db, worker_id):
    from testutils.factories import UserFactory

    def username(instance: "User", step: int) -> str:
        return f"u{step:<03}_{worker_id}@example.com"

    return UserFactory(username=factory.LazyAttributeSequence(username))


@pytest.fixture
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


@pytest.fixture
def active_marks(request: pytest.FixtureRequest):
    # Collect all the marks for this node (test)
    current_node = request.node
    marks = []
    while current_node:
        marks += [mark.name for mark in current_node.iter_markers()]
        current_node = current_node.parent

    # Get the mark expression - what was passed to -m
    mark_expr = request.config.option.markexpr

    # Compile the mark expression
    from _pytest.mark.expression import Expression

    compiled_mark_expr = Expression.compile(mark_expr)

    # Return a sequence of markers that match
    return [mark for mark in marks if compiled_mark_expr.evaluate(lambda candidate: candidate == mark)]  # noqa B023


@pytest.fixture
def force_migrated_records(request, active_marks):
    from country_workspace.versioning.management.manager import Manager

    Manager().force_apply()


@pytest.fixture
def household_checker(request, active_marks):
    from testutils.factories import DataCheckerFactory

    from country_workspace.contrib.hope.constants import HOUSEHOLD_CHECKER_NAME

    return DataCheckerFactory(name=HOUSEHOLD_CHECKER_NAME)


@pytest.fixture
def individual_checker(request, active_marks):
    from testutils.factories import DataCheckerFactory

    from country_workspace.contrib.hope.constants import INDIVIDUAL_CHECKER_NAME

    return DataCheckerFactory(name=INDIVIDUAL_CHECKER_NAME)


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": ["authorization"],
        "cassette_library_dir": str(Path(__file__).parent / "extras/cassettes"),
    }
