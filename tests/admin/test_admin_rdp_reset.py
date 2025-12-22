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

    perm = Permission.objects.get(codename="reset_rdp")
    admin_user.user_permissions.add(perm)

    url = reverse("admin:country_workspace_rdp_reset", args=[rdp.pk])

    # Verify initial state
    household.refresh_from_db()
    individual.refresh_from_db()
    assert household.removed is True
    assert individual.removed is True

    # Perform reset
    res = app.post(url)
    assert res.status_code == 302  # Redirects back

    # Follow redirect to see messages
    res = res.follow()
    assert "RDP reset successfully" in res.text

    # Verify final state
    household.refresh_from_db()
    individual.refresh_from_db()
    assert household.removed is False
    assert individual.removed is False


@pytest.mark.django_db
def test_rdp_reset_fail_wrong_status(app, rdp, household, individual, admin_user):
    # Grant permission
    from django.contrib.auth.models import Permission

    perm = Permission.objects.get(codename="reset_rdp")
    admin_user.user_permissions.add(perm)

    # Set status to something other than SUCCESS
    rdp.status = Rdp.PushStatus.PENDING
    rdp.save()

    url = reverse("admin:country_workspace_rdp_reset", args=[rdp.pk])

    # Perform reset
    res = app.post(url)
    assert res.status_code == 302

    res = res.follow()
    assert "Reset is only allowed for SUCCESS status" in res.text

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

    view_perm = Permission.objects.get(codename="view_rdp")
    admin_user.user_permissions.add(view_perm)

    url = reverse("admin:country_workspace_rdp_reset", args=[rdp.pk])

    res = app.post(url, expect_errors=True)
    assert res.status_code == 403
