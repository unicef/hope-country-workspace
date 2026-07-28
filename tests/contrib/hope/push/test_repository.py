from uuid import uuid4

import pytest
from django.utils import timezone
from pytest_mock import MockerFixture

import country_workspace.contrib.hope.push.repository as repo
from country_workspace.models import Rdp as RdpModel
from testutils.factories import (
    CountryHouseholdFactory,
    CountryIndividualFactory,
    CountryProgramFactory,
    CountryRdpFactory,
    DataSerializerFactory,
    UserFactory,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def program_no_serializer():
    return CountryProgramFactory(serializer=None)


@pytest.fixture
def program_with_serializer():
    return CountryProgramFactory(serializer=DataSerializerFactory())


@pytest.fixture
def pushed_by_user():
    return UserFactory()


@pytest.fixture
def rdp(program_with_serializer, pushed_by_user):
    return CountryRdpFactory(program=program_with_serializer, pushed_by=pushed_by_user)


@pytest.fixture
def hh_with_members():
    hh = CountryHouseholdFactory()
    if not hh.members.exists():
        CountryIndividualFactory.create_batch(2, household=hh)
    return hh


@pytest.fixture
def rdp_with_household_link(program_with_serializer, pushed_by_user):
    rdp = CountryRdpFactory(program=program_with_serializer, pushed_by=pushed_by_user)
    hh = CountryHouseholdFactory(rdps=rdp)
    if not hh.members.exists():
        CountryIndividualFactory.create_batch(2, household=hh)
    return rdp, hh


@pytest.fixture
def rdp_with_individual_links(program_with_serializer, pushed_by_user):
    rdp = CountryRdpFactory(program=program_with_serializer, pushed_by=pushed_by_user)
    individuals = (CountryIndividualFactory(), CountryIndividualFactory())
    for ind in individuals:
        ind.rdp.add(rdp)
    return rdp, individuals


# ----------------------------- RDP lookup -----------------------------


def test_lock_rdp_for_update(mocker: MockerFixture) -> None:
    qs = mocker.MagicMock()
    locked_qs = mocker.MagicMock()
    rdp = mocker.MagicMock()

    select_for_update = mocker.patch.object(repo.Rdp.objects, "select_for_update", return_value=qs)
    qs.select_related.return_value = locked_qs
    locked_qs.get.return_value = rdp

    assert repo.lock_rdp_for_update(pk=123) is rdp

    select_for_update.assert_called_once_with()
    qs.select_related.assert_called_once_with("program")
    locked_qs.get.assert_called_once_with(pk=123)


def test_rdp_for_dedup(mocker: MockerFixture) -> None:
    qs = mocker.MagicMock()
    rdp = mocker.MagicMock()

    select_related = mocker.patch.object(repo.Rdp.objects, "select_related", return_value=qs)
    qs.get.return_value = rdp

    assert repo.rdp_for_dedup(pk=123) is rdp

    select_related.assert_called_once_with("program")
    qs.get.assert_called_once_with(pk=123)


def test_rdp_for_push(mocker: MockerFixture) -> None:
    qs = mocker.MagicMock()
    rdp = mocker.MagicMock()

    select_related = mocker.patch.object(repo.Rdp.objects, "select_related", return_value=qs)
    qs.get.return_value = rdp

    assert repo.rdp_for_push(pk=123) is rdp

    select_related.assert_called_once_with(
        "program__country_office",
        "program__beneficiary_group",
        "pushed_by",
    )
    qs.get.assert_called_once_with(pk=123)


@pytest.mark.parametrize(
    ("hope_rdi_id", "expected"),
    [
        ("RDI-1", "RDI-1"),
        ("N/A", None),
        ("", None),
        (None, None),
    ],
    ids=["real", "na", "empty", "none"],
)
def test_existing_hope_rdi_id(rdp, hope_rdi_id: str | None, expected: str | None) -> None:
    rdp.hope_rdi_id = hope_rdi_id
    rdp.save(update_fields=["hope_rdi_id"])

    assert repo.existing_hope_rdi_id(rdp_id=rdp.pk) == expected


# -------------------------- selection / config -------------------------


def test_rdp_selection_prefers_households(rdp_with_household_link) -> None:
    rdp, hh = rdp_with_household_link

    assert repo.rdp_selection(rdp=rdp) == (True, [hh.pk])


def test_rdp_selection_falls_back_to_individuals(rdp_with_individual_links) -> None:
    rdp, (i1, i2) = rdp_with_individual_links

    assert repo.rdp_selection(rdp=rdp) == (False, [i1.pk, i2.pk])


def test_serializer_for_program_identity_when_none(program_no_serializer) -> None:
    data = [{"a": 1}]

    assert repo.serializer_for_program(program_no_serializer.hope_id)(data) == data


def test_serializer_for_program_uses_serializer(
    mocker: MockerFixture,
    program_with_serializer,
) -> None:
    data = [{"x": 1}]
    expected = [{"y": 2}]
    serializer_cls = type(program_with_serializer.serializer)
    spy = mocker.patch.object(serializer_cls, "serialize", autospec=True, return_value=expected)

    assert repo.serializer_for_program(program_with_serializer.hope_id)(data) == expected
    spy.assert_called_once()


@pytest.mark.parametrize(
    ("fixture_name", "master_detail", "expected_pks"),
    [
        ("rdp_with_household_link", True, lambda selection: [selection.pk]),
        ("rdp_with_individual_links", False, lambda selection: [selection[0].pk, selection[1].pk]),
    ],
    ids=["master_detail", "people_only"],
)
@pytest.mark.parametrize(
    ("biometric_enabled", "has_deduplication_set_id", "expect_country_workspace_id"),
    [
        (False, False, False),
        (False, True, False),
        (True, False, False),
        (True, True, True),
    ],
    ids=[
        "non_biometric_without_dedup_set",
        "non_biometric_with_dedup_set",
        "biometric_without_dedup_set",
        "biometric_with_dedup_set",
    ],
)
def test_workflow_config_for_rdp(
    request: pytest.FixtureRequest,
    fixture_name: str,
    master_detail: bool,
    expected_pks,
    pushed_by_user,
    biometric_enabled: bool,
    has_deduplication_set_id: bool,
    expect_country_workspace_id: bool,
) -> None:
    rdp, selection = request.getfixturevalue(fixture_name)

    rdp.program.biometric_deduplication_enabled = biometric_enabled
    rdp.program.save(update_fields=["biometric_deduplication_enabled"])

    rdp.deduplication_set_id = deduplication_set_id = uuid4() if has_deduplication_set_id else None
    rdp.save(update_fields=["deduplication_set_id"])

    expected = {
        "batch_name": rdp.name,
        "co_slug": rdp.program.country_office.slug,
        "imported_by_email": pushed_by_user.email,
        "master_detail": master_detail,
        "pks": expected_pks(selection),
        "program_hope_id": rdp.program.hope_id,
        "rdp_id": rdp.id,
    }
    if expect_country_workspace_id:
        expected["country_workspace_id"] = str(deduplication_set_id)

    assert repo.workflow_config_for_rdp(rdp=rdp, imported_by_email=pushed_by_user.email) == expected


# ------------------------------- querysets ------------------------------


def test_qs_households_prefetches_members(hh_with_members) -> None:
    households = list(repo.qs_households(pks=[hh_with_members.pk]))

    assert [hh.pk for hh in households] == [hh_with_members.pk]
    assert all(hasattr(hh, "prefetched_members") for hh in households)
    assert [member.pk for member in households[0].prefetched_members] == list(
        hh_with_members.members.order_by("id").values_list("pk", flat=True)
    )


def test_qs_individuals_by_household_pks_orders_by_id(hh_with_members) -> None:
    expected = list(hh_with_members.members.order_by("id").values_list("id", flat=True))

    assert list(repo.qs_individuals_by_household_pks([hh_with_members.pk]).values_list("id", flat=True)) == expected


def test_collector_pks_by_household_pks_returns_role_ref_pks() -> None:
    hh = CountryHouseholdFactory()
    hh.members.all().delete()
    primary = CountryIndividualFactory(household=None)
    alternate = CountryIndividualFactory(household=None)
    hh.flex_fields = {"primary_collector_id": primary.pk, "alternate_collector_id": alternate.pk}
    hh.save(update_fields=["flex_fields"])

    assert repo.collector_pks_by_household_pks([hh.pk]) == {primary.pk, alternate.pk}


def test_collector_pks_by_household_pks_ignores_missing_and_invalid_refs() -> None:
    hh = CountryHouseholdFactory()
    hh.members.all().delete()
    hh.flex_fields = {"primary_collector_id": None, "alternate_collector_id": "not-a-pk"}
    hh.save(update_fields=["flex_fields"])

    assert repo.collector_pks_by_household_pks([hh.pk]) == set()


def test_qs_individuals_for_push_includes_members_and_referenced_collectors() -> None:
    hh = CountryHouseholdFactory()
    hh.members.all().delete()
    member = CountryIndividualFactory(household=hh)
    collector = CountryIndividualFactory(household=None, flex_fields={"relationship": "NON_BENEFICIARY"})
    unreferenced = CountryIndividualFactory(household=None)
    hh.flex_fields = {"primary_collector_id": collector.pk}
    hh.save(update_fields=["flex_fields"])

    result = set(repo.qs_individuals_for_push([hh.pk]).values_list("id", flat=True))

    assert result == {member.pk, collector.pk}
    assert unreferenced.pk not in result


def test_qs_individuals_by_pks_orders_by_id() -> None:
    individuals = [CountryIndividualFactory() for _ in range(3)]
    pks = [individuals[2].pk, individuals[0].pk]
    expected = sorted([individuals[0].pk, individuals[2].pk])

    assert list(repo.qs_individuals_by_pks(pks).values_list("id", flat=True)) == expected


@pytest.mark.parametrize(
    ("master_detail", "expected"),
    [(True, "by_households"), (False, "by_pks")],
    ids=["master_detail", "flat"],
)
def test_qs_individuals_for_rdp_delegates(
    mocker: MockerFixture,
    rdp,
    master_detail: bool,
    expected: str,
) -> None:
    mocker.patch.object(repo, "rdp_selection", return_value=(master_detail, [1, 2]))
    by_households = mocker.patch.object(repo, "qs_individuals_by_household_pks", return_value="hh_qs")
    by_pks = mocker.patch.object(repo, "qs_individuals_by_pks", return_value="ind_qs")

    result = repo.qs_individuals_for_rdp(rdp=rdp)

    if expected == "by_households":
        assert result == "hh_qs"
        by_households.assert_called_once_with([1, 2])
        by_pks.assert_not_called()
    else:
        assert result == "ind_qs"
        by_pks.assert_called_once_with([1, 2])
        by_households.assert_not_called()


# ------------------------------- preflight ------------------------------


@pytest.mark.parametrize("master_detail", [True, False], ids=["master_detail", "flat"])
def test_preflight_errors_rejects_empty_selection(master_detail: bool) -> None:
    assert repo.preflight_errors(pks=[], master_detail=master_detail) == ["RDP: no beneficiaries selected"]


def test_preflight_errors_flat() -> None:
    invalid = CountryIndividualFactory(last_checked=None, errors={})
    linked = CountryIndividualFactory(last_checked=timezone.now(), errors={})
    linked.rdp.add(CountryRdpFactory(status=RdpModel.PushStatus.SUCCESS))

    errors = repo.preflight_errors(pks=[invalid.pk, linked.pk], master_detail=False)

    assert f"Ind #{invalid.pk} invalid" in errors
    assert any(f"Ind #{linked.pk}" in error and "already in another RDP" in error for error in errors)


def test_preflight_errors_master_detail() -> None:
    invalid = CountryHouseholdFactory(last_checked=None, errors={})
    invalid_member = CountryIndividualFactory(household=invalid, last_checked=None, errors={})

    linked = CountryHouseholdFactory(last_checked=timezone.now(), errors={})
    linked_member = CountryIndividualFactory(household=linked, last_checked=timezone.now(), errors={})
    rdp = CountryRdpFactory(status=RdpModel.PushStatus.SUCCESS)
    linked.rdp.add(rdp)
    linked_member.rdp.add(rdp)

    errors = repo.preflight_errors(pks=[invalid.pk, linked.pk], master_detail=True)

    assert f"HH #{invalid.pk} invalid" in errors
    assert f"Ind #{invalid_member.pk} invalid" in errors
    assert any(f"HH #{linked.pk}" in error and "already in another RDP" in error for error in errors)
    assert any(f"Ind #{linked_member.pk}" in error and "already in another RDP" in error for error in errors)


def test_preflight_errors_excludes_rdp_ids() -> None:
    individual = CountryIndividualFactory(last_checked=timezone.now(), errors={})
    rdp = CountryRdpFactory(status=RdpModel.PushStatus.SUCCESS)
    individual.rdp.add(rdp)

    assert (
        repo.preflight_errors(
            pks=[individual.pk],
            master_detail=False,
            exclude_rdp_ids=[rdp.pk],
        )
        == []
    )


def test_preflight_errors_master_detail_covers_referenced_collectors() -> None:
    hh = CountryHouseholdFactory(last_checked=timezone.now(), errors={})
    hh.members.all().delete()
    collector = CountryIndividualFactory(household=None, last_checked=None, errors={})
    hh.flex_fields = {"primary_collector_id": collector.pk}
    hh.save(update_fields=["flex_fields"])

    errors = repo.preflight_errors(pks=[hh.pk], master_detail=True)

    assert f"Ind #{collector.pk} invalid" in errors


# --------------------------- status / locks / log -----------------------


@pytest.mark.parametrize(
    ("extra_kwargs", "expected_dedup_locked", "expected_push_locked", "expected_update_fields"),
    [
        ({}, True, True, ["status", "hope_rdi_id"]),
        ({"is_dedup_settings_locked": False}, False, True, ["status", "hope_rdi_id", "is_dedup_settings_locked"]),
        ({"is_push_locked": False}, True, False, ["status", "hope_rdi_id", "is_push_locked"]),
        (
            {"is_dedup_settings_locked": False, "is_push_locked": False},
            False,
            False,
            ["status", "hope_rdi_id", "is_dedup_settings_locked", "is_push_locked"],
        ),
    ],
    ids=["preserve_locks", "unlock_dedup", "unlock_push", "unlock_both"],
)
def test_set_rdp_push_status(
    mocker: MockerFixture,
    rdp,
    extra_kwargs: dict,
    expected_dedup_locked: bool,
    expected_push_locked: bool,
    expected_update_fields: list[str],
) -> None:
    rdp.is_dedup_settings_locked = True
    rdp.is_push_locked = True
    rdp.save(update_fields=["is_dedup_settings_locked", "is_push_locked"])
    save = mocker.patch.object(rdp, "save", wraps=rdp.save)

    repo.set_rdp_push_status(
        rdp=rdp,
        status=RdpModel.PushStatus.SUCCESS,
        hope_rdi_id="RDI-1",
        **extra_kwargs,
    )

    save.assert_called_once_with(update_fields=expected_update_fields)

    rdp.refresh_from_db()
    assert rdp.status == RdpModel.PushStatus.SUCCESS
    assert rdp.hope_rdi_id == "RDI-1"
    assert rdp.is_dedup_settings_locked is expected_dedup_locked
    assert rdp.is_push_locked is expected_push_locked


def test_release_rdp_push_lock(rdp) -> None:
    rdp.is_push_locked = True
    rdp.save(update_fields=["is_push_locked"])

    repo.release_rdp_push_lock(rdp_id=rdp.pk)

    rdp.refresh_from_db()
    assert rdp.is_push_locked is False


def test_release_rdp_dedup_settings_lock(rdp) -> None:
    rdp.is_dedup_settings_locked = True
    rdp.save(update_fields=["is_dedup_settings_locked"])

    repo.release_rdp_dedup_settings_lock(rdp_id=rdp.pk)

    rdp.refresh_from_db()
    assert rdp.is_dedup_settings_locked is False


def test_append_rdp_operation_log(mocker: MockerFixture, rdp) -> None:
    now = timezone.now()
    mocker.patch.object(repo.timezone, "now", return_value=now)

    repo.append_rdp_operation_log(
        rdp=rdp,
        action=RdpModel.OperationAction.START_DEDUPLICATION,
        job_id=123,
        result={"ok": True},
    )

    rdp.refresh_from_db()
    assert rdp.operation_log == [
        {
            "timestamp": now.isoformat(),
            "action": RdpModel.OperationAction.START_DEDUPLICATION.value,
            "job_id": 123,
            "result": {"ok": True},
        }
    ]
