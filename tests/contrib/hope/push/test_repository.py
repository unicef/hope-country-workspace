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
def parent_rdp(program_with_serializer, pushed_by_user):
    return CountryRdpFactory(program=program_with_serializer, pushed_by=pushed_by_user)


@pytest.fixture
def child_rdp(parent_rdp):
    return CountryRdpFactory(
        program=parent_rdp.program,
        pushed_by=parent_rdp.pushed_by,
        parent=parent_rdp,
    )


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

    select_related.assert_called_once_with("program", "parent")
    qs.get.assert_called_once_with(pk=123)


def test_rdp_for_push(mocker: MockerFixture) -> None:
    qs = mocker.MagicMock()
    rdp = mocker.MagicMock()

    select_related = mocker.patch.object(repo.Rdp.objects, "select_related", return_value=qs)
    qs.get.return_value = rdp

    assert repo.rdp_for_push(pk=123) is rdp

    select_related.assert_called_once_with(
        "parent",
        "program__country_office",
        "program__beneficiary_group",
        "pushed_by",
    )
    qs.get.assert_called_once_with(pk=123)


def test_lock_rdp_for_hope_callback(mocker: MockerFixture) -> None:
    qs = mocker.MagicMock()
    rdp = mocker.MagicMock()

    select_for_update = mocker.patch.object(repo.Rdp.objects, "select_for_update", return_value=qs)
    qs.get.return_value = rdp

    assert repo.lock_rdp_for_hope_callback(hope_rdi_id="RDI-1") is rdp

    select_for_update.assert_called_once_with()
    qs.get.assert_called_once_with(hope_rdi_id="RDI-1")


def test_selection_owner_for_rdp_returns_self(rdp) -> None:
    assert repo.selection_owner_for_rdp(rdp=rdp) == rdp


def test_selection_owner_for_rdp_returns_parent(child_rdp, parent_rdp) -> None:
    assert repo.selection_owner_for_rdp(rdp=child_rdp) == parent_rdp


def test_preflight_exclude_rdp_ids_without_input() -> None:
    assert repo.preflight_exclude_rdp_ids() == ()


def test_preflight_exclude_rdp_ids_from_rdp_without_parent(rdp) -> None:
    assert repo.preflight_exclude_rdp_ids(rdp=rdp) == (rdp.pk,)


def test_preflight_exclude_rdp_ids_from_rdp_with_parent(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock(pk=10, parent_id=20)

    assert repo.preflight_exclude_rdp_ids(rdp=rdp) == (10, 20)


def test_preflight_exclude_rdp_ids_from_rdp_id(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock(pk=10, parent_id=20)
    only_qs = mocker.MagicMock()

    only = mocker.patch.object(repo.Rdp.objects, "only", return_value=only_qs)
    only_qs.get.return_value = rdp

    assert repo.preflight_exclude_rdp_ids(rdp_id=10) == (10, 20)

    only.assert_called_once_with("id", "parent_id")
    only_qs.get.assert_called_once_with(pk=10)


def test_rdp_selection_prefers_households(rdp_with_household_link) -> None:
    rdp, hh = rdp_with_household_link

    assert repo.rdp_selection(rdp=rdp) == (True, [hh.pk])


def test_rdp_selection_falls_back_to_individuals(rdp_with_individual_links) -> None:
    rdp, (i1, i2) = rdp_with_individual_links

    assert repo.rdp_selection(rdp=rdp) == (False, [i1.pk, i2.pk])


def test_rdp_selection_uses_owner_selection(parent_rdp, child_rdp) -> None:
    hh = CountryHouseholdFactory(rdps=parent_rdp)
    if not hh.members.exists():
        CountryIndividualFactory.create_batch(2, household=hh)

    assert repo.rdp_selection(rdp=child_rdp) == (True, [hh.pk])


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


@pytest.mark.parametrize("master_detail", [True, False], ids=["master_detail", "flat"])
def test_preflight_errors_rejects_empty_selection(master_detail: bool) -> None:
    assert repo.preflight_errors(pks=[], master_detail=master_detail) == ["RDP: no beneficiaries selected"]


def test_preflight_errors_flat() -> None:
    invalid = CountryIndividualFactory(last_checked=None, errors={})
    linked = CountryIndividualFactory(last_checked=timezone.now(), errors={})
    linked.rdp.add(CountryRdpFactory(status=RdpModel.PushStatus.PUSHED))

    assert repo.preflight_errors(pks=[invalid.pk, linked.pk], master_detail=False) == [
        f"Ind #{invalid.pk} invalid",
        f"Ind #{linked.pk} already in another RDP(s) (pending/pushed/merged)",
    ]


def test_preflight_errors_master_detail() -> None:
    invalid = CountryHouseholdFactory(last_checked=None, errors={})
    invalid_member = CountryIndividualFactory(household=invalid, last_checked=None, errors={})

    linked = CountryHouseholdFactory(last_checked=timezone.now(), errors={})
    linked_member = CountryIndividualFactory(household=linked, last_checked=timezone.now(), errors={})
    rdp = CountryRdpFactory(status=RdpModel.PushStatus.PUSHED)
    linked.rdp.add(rdp)
    linked_member.rdp.add(rdp)

    errors = repo.preflight_errors(pks=[invalid.pk, linked.pk], master_detail=True)

    assert f"HH #{invalid.pk} invalid" in errors
    assert f"HH #{linked.pk} already in another RDP(s) (pending/pushed/merged)" in errors
    assert f"Ind #{invalid_member.pk} invalid" in errors
    assert f"Ind #{linked_member.pk} already in another RDP(s) (pending/pushed/merged)" in errors


def test_preflight_errors_excludes_rdp_ids() -> None:
    individual = CountryIndividualFactory(last_checked=timezone.now(), errors={})
    rdp = CountryRdpFactory(status=RdpModel.PushStatus.PUSHED)
    individual.rdp.add(rdp)

    assert (
        repo.preflight_errors(
            pks=[individual.pk],
            master_detail=False,
            exclude_rdp_ids=[rdp.pk],
        )
        == []
    )


@pytest.mark.parametrize(
    ("initial", "key", "snapshot", "expected"),
    [
        (
            None,
            "before_push",
            {"deduplication_set_status": "Deduplicated", "findings_count": 3},
            {"before_push": {"deduplication_set_status": "Deduplicated", "findings_count": 3}},
        ),
        (
            {"before_clone": {"deduplication_set_status": "Ready", "findings_count": 0}},
            "before_push",
            {"deduplication_set_status": "Deduplicated", "findings_count": 3},
            {
                "before_clone": {"deduplication_set_status": "Ready", "findings_count": 0},
                "before_push": {"deduplication_set_status": "Deduplicated", "findings_count": 3},
            },
        ),
        (
            {"before_push": {"deduplication_set_status": "Ready", "findings_count": 0}},
            "before_push",
            {"deduplication_set_status": "Deduplicated", "findings_count": 3},
            {"before_push": {"deduplication_set_status": "Deduplicated", "findings_count": 3}},
        ),
    ],
    ids=["empty", "merge", "overwrite"],
)
def test_set_rdp_deduplication_snapshot(
    mocker: MockerFixture,
    rdp,
    initial,
    key: str,
    snapshot: dict,
    expected: dict,
) -> None:
    rdp.deduplication_snapshots = initial
    save = mocker.patch.object(rdp, "save", wraps=rdp.save)

    repo.set_rdp_deduplication_snapshot(rdp=rdp, key=key, snapshot=snapshot)

    save.assert_called_once_with(update_fields=["deduplication_snapshots"])
    assert rdp.deduplication_snapshots == expected

    rdp.refresh_from_db()
    assert rdp.deduplication_snapshots == expected


@pytest.mark.parametrize(
    ("lock_value", "expected_locked", "expected_update_fields"),
    [
        (None, True, ["status", "hope_rdi_id"]),
        (False, False, ["status", "hope_rdi_id", "is_dedup_settings_locked"]),
        (True, True, ["status", "hope_rdi_id", "is_dedup_settings_locked"]),
    ],
    ids=["preserve_lock", "unlock", "lock"],
)
def test_set_rdp_push_status(
    mocker: MockerFixture,
    rdp,
    lock_value: bool | None,
    expected_locked: bool,
    expected_update_fields: list[str],
) -> None:
    rdp.is_dedup_settings_locked = True
    rdp.save(update_fields=["is_dedup_settings_locked"])
    save = mocker.patch.object(rdp, "save", wraps=rdp.save)

    kwargs = {
        "rdp": rdp,
        "status": RdpModel.PushStatus.PUSHED,
        "hope_rdi_id": "RDI-1",
    }
    if lock_value is not None:
        kwargs["is_dedup_settings_locked"] = lock_value

    repo.set_rdp_push_status(**kwargs)

    save.assert_called_once_with(update_fields=expected_update_fields)

    rdp.refresh_from_db()
    assert rdp.status == RdpModel.PushStatus.PUSHED
    assert rdp.hope_rdi_id == "RDI-1"
    assert rdp.is_dedup_settings_locked is expected_locked


def test_has_other_pending_rdp(program_with_serializer, pushed_by_user) -> None:
    owner = CountryRdpFactory(
        program=program_with_serializer,
        pushed_by=pushed_by_user,
        status=RdpModel.PushStatus.PUSHED,
    )
    CountryRdpFactory(
        program=program_with_serializer,
        pushed_by=pushed_by_user,
        status=RdpModel.PushStatus.PENDING,
    )

    assert repo.has_other_pending_rdp(owner=owner) is True


def test_has_other_pending_rdp_respects_exclude_ids(program_with_serializer, pushed_by_user) -> None:
    owner = CountryRdpFactory(
        program=program_with_serializer,
        pushed_by=pushed_by_user,
        status=RdpModel.PushStatus.PUSHED,
    )
    other = CountryRdpFactory(
        program=program_with_serializer,
        pushed_by=pushed_by_user,
        status=RdpModel.PushStatus.PENDING,
    )

    assert repo.has_other_pending_rdp(owner=owner, exclude_ids=[other.pk]) is False


def test_has_other_pending_rdp_ignores_non_pending(program_with_serializer, pushed_by_user) -> None:
    owner = CountryRdpFactory(
        program=program_with_serializer,
        pushed_by=pushed_by_user,
        status=RdpModel.PushStatus.MERGED,
    )
    CountryRdpFactory(
        program=program_with_serializer,
        pushed_by=pushed_by_user,
        status=RdpModel.PushStatus.MERGED,
    )

    assert repo.has_other_pending_rdp(owner=owner) is False
