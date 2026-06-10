from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from pytest_mock import MockerFixture
from strategy_field.utils import fqn

from country_workspace.contrib.hope.push.orchestration import reset_rdp_core
from country_workspace.models import AsyncJob, Rdp

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.models import User


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    return OfficeFactory()


@pytest.fixture
def program(office):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(country_office=office)


@pytest.fixture
def rdp(program):
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(program=program, status=Rdp.PushStatus.PUSHED, hope_rdi_id="RID-1")


@pytest.fixture
def household(rdp):
    from testutils.factories import HouseholdFactory

    hh = HouseholdFactory(batch__program=rdp.program)
    hh.rdp.add(rdp)
    hh.removed = True
    hh.save(update_fields=["removed"])
    return hh


@pytest.fixture
def individual(rdp, household):
    from testutils.factories import IndividualFactory

    ind = IndividualFactory(batch__program=rdp.program, household=household)
    ind.rdp.add(rdp)
    ind.removed = True
    ind.save(update_fields=["removed"])
    return ind


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


@pytest.fixture
def reset_permission(admin_user):
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    content_type = ContentType.objects.get_for_model(Rdp)
    permission, _ = Permission.objects.get_or_create(
        codename="reset_rdp",
        content_type=content_type,
        defaults={"name": "Can reset RDP"},
    )
    admin_user.user_permissions.add(permission)
    return permission


@pytest.mark.django_db
def test_rdp_reset_success(
    app,
    rdp,
    household,
    individual,
    reset_permission,
    mocker: MockerFixture,
) -> None:
    url = reverse("admin:country_workspace_rdp_reset", args=[rdp.pk])
    on_commit = mocker.patch("country_workspace.admin.rdp.transaction.on_commit")

    household.refresh_from_db()
    individual.refresh_from_db()
    assert household.removed is True
    assert individual.removed is True

    res = app.post(url)
    assert res.status_code == 302

    res = res.follow()
    messages = list(res.context["messages"])
    assert any("RDP reset task scheduled" in str(message) for message in messages)

    jobs = AsyncJob.objects.filter(rdp=rdp)
    assert jobs.count() == 1
    job = jobs.get()

    assert job.description.startswith("Reset pushed RDP after manual HOPE rejection confirmation")
    assert job.type == AsyncJob.JobType.TASK
    assert job.action == fqn(reset_rdp_core)
    assert job.program == rdp.program
    assert job.config == {"rdp_id": rdp.pk}

    on_commit.assert_called_once()
    callback = on_commit.call_args.args[0]
    assert callback.__name__ == "queue"
    assert callback.__self__.pk == job.pk

    household.refresh_from_db()
    individual.refresh_from_db()
    rdp.refresh_from_db()
    assert household.removed is True
    assert individual.removed is True
    assert rdp.status == Rdp.PushStatus.PUSHED


@pytest.mark.django_db
def test_rdp_reset_fail_wrong_status(app, rdp, household, individual, reset_permission) -> None:
    rdp.status = Rdp.PushStatus.PENDING
    rdp.save(update_fields=["status"])

    res = app.post(reverse("admin:country_workspace_rdp_reset", args=[rdp.pk]))
    assert res.status_code == 302

    res = res.follow()
    messages = list(res.context["messages"])
    assert any("Reset is only allowed for PUSHED status" in str(message) for message in messages)

    household.refresh_from_db()
    individual.refresh_from_db()
    rdp.refresh_from_db()
    assert household.removed is True
    assert individual.removed is True
    assert rdp.status == Rdp.PushStatus.PENDING
    assert not AsyncJob.objects.filter(rdp=rdp).exists()


@pytest.mark.django_db
def test_rdp_reset_no_permission(app, rdp, admin_user):
    admin_user.is_superuser = False
    admin_user.save(update_fields=["is_superuser"])

    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    content_type = ContentType.objects.get_for_model(Rdp)
    view_perm, _ = Permission.objects.get_or_create(
        codename="view_rdp",
        content_type=content_type,
        defaults={"name": "Can view RDP"},
    )
    admin_user.user_permissions.add(view_perm)

    res = app.post(reverse("admin:country_workspace_rdp_reset", args=[rdp.pk]), expect_errors=True)

    assert res.status_code == 403
