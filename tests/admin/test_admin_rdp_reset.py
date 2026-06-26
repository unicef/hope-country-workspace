import pytest
from django.urls import reverse
from typing import TYPE_CHECKING
from country_workspace.models import Rdp

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

    return CountryRdpFactory(program=program, status=Rdp.PushStatus.SUCCESS)


@pytest.fixture
def household(rdp):
    from testutils.factories import HouseholdFactory

    hh = HouseholdFactory(batch__program=rdp.program)
    hh.rdp.add(rdp)
    hh.removed = True
    hh.save()
    return hh


@pytest.fixture
def individual(rdp, household):
    from testutils.factories import IndividualFactory

    ind = IndividualFactory(batch__program=rdp.program, household=household)
    ind.rdp.add(rdp)
    ind.removed = True
    ind.save()
    return ind


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


@pytest.mark.django_db
def test_rdp_reset_success(app, rdp, household, individual, admin_user):
    # Grant permission
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    content_type = ContentType.objects.get_for_model(Rdp)
    perm, _ = Permission.objects.get_or_create(
        codename="reset_rdp", content_type=content_type, defaults={"name": "Can reset RDP"}
    )
    admin_user.user_permissions.add(perm)

    url = reverse("admin:country_workspace_rdp_reset", args=[rdp.pk])

    # Verify initial state
    household.refresh_from_db()
    individual.refresh_from_db()
    assert household.removed is True
    assert individual.removed is True

    # First POST shows confirmation page
    res = app.post(url)
    assert res.status_code == 302

    # Second POST confirms and performs the action
    res = app.post(url)
    assert res.status_code == 302  # Redirects back

    # Follow redirect to see messages
    res = res.follow()

    messages = list(res.context["messages"])
    assert len(messages) >= 1
    assert any("RDP reset successfully" in str(m) for m in messages)

    # Verify final state
    household.refresh_from_db()
    individual.refresh_from_db()
    rdp.refresh_from_db()
    assert household.removed is False
    assert individual.removed is False
    assert rdp.status == Rdp.PushStatus.CANCELLED


@pytest.mark.django_db
def test_rdp_reset_fail_wrong_status(app, rdp, household, individual, admin_user):
    # Grant permission
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    content_type = ContentType.objects.get_for_model(Rdp)
    perm, _ = Permission.objects.get_or_create(
        codename="reset_rdp", content_type=content_type, defaults={"name": "Can reset RDP"}
    )
    admin_user.user_permissions.add(perm)

    # Set status to something other than SUCCESS
    rdp.status = Rdp.PushStatus.PENDING
    rdp.save()

    url = reverse("admin:country_workspace_rdp_reset", args=[rdp.pk])

    # Perform reset
    res = app.post(url)
    assert res.status_code == 302

    res = res.follow()

    messages = list(res.context["messages"])
    assert len(messages) >= 1
    assert any("Reset is only allowed for SUCCESS status" in str(m) for m in messages)

    # Verify state was NOT changed
    household.refresh_from_db()
    individual.refresh_from_db()
    assert household.removed is True
    assert individual.removed is True


@pytest.mark.django_db
def test_rdp_reset_no_permission(app, rdp, admin_user):
    admin_user.is_superuser = False
    admin_user.save()
    # Ensure they have access to admin panel at least
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    # Add view permission for Rdp
    content_type = ContentType.objects.get_for_model(Rdp)
    view_perm, _ = Permission.objects.get_or_create(
        codename="view_rdp", content_type=content_type, defaults={"name": "Can view RDP"}
    )
    admin_user.user_permissions.add(view_perm)

    url = reverse("admin:country_workspace_rdp_reset", args=[rdp.pk])

    # Perform reset - should be 403 Forbidden
    res = app.post(url, expect_errors=True)
    assert res.status_code == 403
