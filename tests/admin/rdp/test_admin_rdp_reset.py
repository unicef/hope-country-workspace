from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from django.urls import reverse
from pytest_mock import MockerFixture

from country_workspace.models import Rdp

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    app = django_app_factory(csrf_checks=False)
    app.set_user(admin_user)
    return app


@pytest.fixture
def rdp() -> Rdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(
        status=Rdp.PushStatus.SUCCESS,
        program__beneficiary_group__master_detail=True,
    )


@pytest.fixture
def records(rdp: Rdp):
    from testutils.factories import HouseholdFactory, IndividualFactory

    household = HouseholdFactory(batch__program=rdp.program, removed=True)
    individual = IndividualFactory(batch__program=rdp.program, household=household, removed=True)
    household.rdp.add(rdp)
    individual.rdp.add(rdp)
    return household, individual


@pytest.fixture
def confirm_reset(mocker: MockerFixture) -> MagicMock:
    return mocker.patch(
        "country_workspace.admin.rdp.confirm_action",
        side_effect=lambda _admin, request, action, *_args, **_kwargs: action(request),
    )


def test_rdp_reset_success(app: "CWTestApp", rdp: Rdp, records, confirm_reset: MagicMock) -> None:
    app.post(reverse("admin:country_workspace_rdp_reset", args=[rdp.pk]))

    household, individual = records
    household.refresh_from_db()
    individual.refresh_from_db()
    rdp.refresh_from_db()

    assert (household.removed, individual.removed, rdp.status) == (
        False,
        False,
        Rdp.PushStatus.CANCELLED,
    )


def test_rdp_reset_rejects_non_success_status(
    app: "CWTestApp",
    rdp: Rdp,
    records,
    confirm_reset: MagicMock,
) -> None:
    rdp.status = Rdp.PushStatus.PENDING
    rdp.save(update_fields=["status"])

    app.post(reverse("admin:country_workspace_rdp_reset", args=[rdp.pk]))

    household, individual = records
    household.refresh_from_db()
    individual.refresh_from_db()
    rdp.refresh_from_db()

    assert (household.removed, individual.removed, rdp.status) == (
        True,
        True,
        Rdp.PushStatus.PENDING,
    )
    confirm_reset.assert_not_called()


def test_rdp_reset_rejects_non_latest_successful_rdp(
    app: "CWTestApp",
    rdp: Rdp,
    records,
    confirm_reset: MagicMock,
) -> None:
    from testutils.factories import CountryRdpFactory

    CountryRdpFactory(program=rdp.program, status=Rdp.PushStatus.SUCCESS, push_date=rdp.push_date)

    app.post(reverse("admin:country_workspace_rdp_reset", args=[rdp.pk]))

    household, individual = records
    household.refresh_from_db()
    individual.refresh_from_db()
    rdp.refresh_from_db()

    assert (household.removed, individual.removed, rdp.status) == (
        True,
        True,
        Rdp.PushStatus.SUCCESS,
    )
    confirm_reset.assert_not_called()


def test_rdp_reset_requires_permission(app: "CWTestApp", rdp: Rdp, admin_user: "User") -> None:
    admin_user.is_superuser = False
    admin_user.save(update_fields=["is_superuser"])

    res = app.post(reverse("admin:country_workspace_rdp_reset", args=[rdp.pk]), expect_errors=True)

    assert res.status_code == 403
