import pytest
from datetime import timedelta
from django.utils import timezone
from constance import config as constance_config
from country_workspace.models import Household, Individual, Rdp
from country_workspace.tasks import cleanup_merged_rdp_data
from tests.extras.testutils.factories import (
    ProgramFactory,
    BatchFactory,
    HouseholdFactory,
    IndividualFactory,
    RdpFactory,
)


@pytest.mark.django_db
def test_cleanup_merged_rdp_data_task():
    program = ProgramFactory.create()
    batch = BatchFactory.create(program=program)

    # Set threshold to 1 day
    constance_config.RDP_CLEANUP_DAYS = 1

    # 1. Successful RDP pushed 2 days ago (Should be cleaned up)
    old_date = timezone.now() - timedelta(days=2)
    rdp_old_success = RdpFactory.create(program=program, status=Rdp.PushStatus.SUCCESS)
    # We need to manually update push_date because auto_now=True
    Rdp.objects.filter(pk=rdp_old_success.pk).update(push_date=old_date)
    rdp_old_success.refresh_from_db()

    hh_old = HouseholdFactory.create(batch=batch, individuals=[], removed=True)
    ind_old = IndividualFactory.create(household=hh_old, removed=True)
    hh_old.rdp.add(rdp_old_success)
    ind_old.rdp.add(rdp_old_success)

    # 2. Successful RDP pushed today (Should NOT be cleaned up)
    rdp_recent_success = RdpFactory.create(program=program, status=Rdp.PushStatus.SUCCESS)
    hh_recent = HouseholdFactory.create(batch=batch, individuals=[], removed=True)
    ind_recent = IndividualFactory.create(household=hh_recent, removed=True)
    hh_recent.rdp.add(rdp_recent_success)
    ind_recent.rdp.add(rdp_recent_success)

    # 3. Pending RDP pushed 2 days ago (Should NOT be cleaned up)
    program_pending = ProgramFactory.create()
    batch_pending = BatchFactory.create(program=program_pending)
    rdp_old_pending = RdpFactory.create(program=program_pending, status=Rdp.PushStatus.PENDING)
    Rdp.objects.filter(pk=rdp_old_pending.pk).update(push_date=old_date)

    hh_pending = HouseholdFactory.create(batch=batch_pending, individuals=[], removed=True)
    ind_pending = IndividualFactory.create(household=hh_pending, removed=True)
    hh_pending.rdp.add(rdp_old_pending)
    ind_pending.rdp.add(rdp_old_pending)

    # 4. Household in BOTH old success and pending RDP (Should NOT be cleaned up)
    # We use a third program for the second pending RDP
    program_multi = ProgramFactory.create()
    batch_multi = BatchFactory.create(program=program_multi)
    rdp_old_success_2 = RdpFactory.create(program=program_multi, status=Rdp.PushStatus.SUCCESS)
    Rdp.objects.filter(pk=rdp_old_success_2.pk).update(push_date=old_date)
    rdp_pending_2 = RdpFactory.create(program=program_multi, status=Rdp.PushStatus.PENDING)

    hh_multi = HouseholdFactory.create(batch=batch_multi, individuals=[], removed=True)
    hh_multi.rdp.add(rdp_old_success_2, rdp_pending_2)

    # 5. Household in old success RDP but removed=False (Should NOT be cleaned up)
    rdp_old_success_3 = RdpFactory.create(program=program, status=Rdp.PushStatus.SUCCESS)
    Rdp.objects.filter(pk=rdp_old_success_3.pk).update(push_date=old_date)
    hh_not_removed = HouseholdFactory.create(batch=batch, individuals=[], removed=False)
    hh_not_removed.rdp.add(rdp_old_success_3)

    # Initial counts
    assert Household.objects.count() == 5
    assert Individual.objects.count() == 3

    # Run task
    cleanup_merged_rdp_data()

    # Final counts
    assert Household.objects.count() == 4
    assert Individual.objects.count() == 2

    assert not Household.objects.filter(pk=hh_old.pk).exists()
    assert Household.objects.filter(pk=hh_recent.pk).exists()
    assert Household.objects.filter(pk=hh_pending.pk).exists()
    assert Household.objects.filter(pk=hh_multi.pk).exists()
    assert Household.objects.filter(pk=hh_not_removed.pk).exists()


@pytest.mark.django_db
def test_cleanup_merged_rdp_data_disabled():
    constance_config.RDP_CLEANUP_DAYS = 0

    program = ProgramFactory.create()
    old_date = timezone.now() - timedelta(days=10)
    rdp_old_success = RdpFactory.create(program=program, status=Rdp.PushStatus.SUCCESS)
    Rdp.objects.filter(pk=rdp_old_success.pk).update(push_date=old_date)

    batch = BatchFactory.create(program=program)
    hh = HouseholdFactory.create(batch=batch, individuals=[], removed=True)
    hh.rdp.add(rdp_old_success)

    cleanup_merged_rdp_data()

    assert Household.objects.filter(pk=hh.pk).exists()


@pytest.mark.django_db
def test_cleanup_merged_rdp_data_no_old_rdps():
    # threshold = 10 days, but RDP is only 5 days old
    constance_config.RDP_CLEANUP_DAYS = 10

    program = ProgramFactory.create()
    old_date = timezone.now() - timedelta(days=5)
    rdp_success = RdpFactory.create(program=program, status=Rdp.PushStatus.SUCCESS)
    Rdp.objects.filter(pk=rdp_success.pk).update(push_date=old_date)

    batch = BatchFactory.create(program=program)
    hh = HouseholdFactory.create(batch=batch, individuals=[], removed=True)
    hh.rdp.add(rdp_success)

    cleanup_merged_rdp_data()

    assert Household.objects.filter(pk=hh.pk).exists()
