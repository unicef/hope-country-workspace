import pytest
from django.utils import timezone

from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.models import Rdp
from country_workspace.rdp.validation import preflight_errors


pytestmark = pytest.mark.django_db


def test_preflight_errors_empty_selection() -> None:
    assert preflight_errors(pks=[], master_detail=False)


def test_preflight_errors_people() -> None:
    from testutils.factories import CountryIndividualFactory, CountryRdpFactory

    unchecked = CountryIndividualFactory(last_checked=None, errors={})
    invalid = CountryIndividualFactory(last_checked=timezone.now(), errors={"field": ["error"]})
    linked = CountryIndividualFactory(last_checked=timezone.now(), errors={})
    linked.rdp.add(CountryRdpFactory(status=Rdp.PushStatus.SUCCESS))

    errors = preflight_errors(
        pks=[unchecked.pk, invalid.pk, linked.pk],
        master_detail=False,
    )

    assert any(f"Ind #{unchecked.pk}" in error and "invalid" in error for error in errors)
    assert any(f"Ind #{invalid.pk}" in error and "invalid" in error for error in errors)
    assert any(f"Ind #{linked.pk}" in error and "another RDP" in error for error in errors)


def test_preflight_errors_ignores_cancelled_and_excluded_rdp() -> None:
    from testutils.factories import CountryIndividualFactory, CountryRdpFactory

    individual = CountryIndividualFactory(last_checked=timezone.now(), errors={})
    excluded = CountryRdpFactory(status=Rdp.PushStatus.SUCCESS)
    cancelled = CountryRdpFactory(status=Rdp.PushStatus.CANCELLED)
    individual.rdp.add(excluded, cancelled)

    assert (
        preflight_errors(
            pks=[individual.pk],
            master_detail=False,
            exclude_rdp_ids=(excluded.pk,),
        )
        == []
    )


def test_preflight_errors_master_detail_includes_households_members_and_collectors() -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    household = CountryHouseholdFactory(individuals=0, last_checked=None, errors={})
    member = CountryIndividualFactory(household=household, last_checked=None, errors={})
    collector = CountryIndividualFactory(household=None, last_checked=None, errors={})
    household.flex_fields = {
        HOUSEHOLD_ROLE_REF_FIELDS.primary_collector: collector.pk,
    }
    household.save(update_fields=["flex_fields"])

    errors = preflight_errors(pks=[household.pk], master_detail=True)

    assert any(f"HH #{household.pk}" in error and "invalid" in error for error in errors)
    assert any(f"Ind #{member.pk}" in error and "invalid" in error for error in errors)
    assert any(f"Ind #{collector.pk}" in error and "invalid" in error for error in errors)
