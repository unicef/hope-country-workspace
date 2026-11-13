import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine.biographic import dataset_status
from country_workspace.contrib.dedup_engine.biographic.dataset_status import (
    NON_BLOCKING_DATASET_STATES,
    PROCESSABLE_DATASET_STATES,
    REJECTABLE_DATASET_STATES,
    RUNNING_DATASET_STATES,
    DatasetState,
    parse_dataset_state,
    retrieve_dataset_state,
)
from country_workspace.exceptions import RemoteError

DATASET_ID = "5f1d3a0e-8c0b-4f5e-9d7a-2b6c1e4a9f10"


@pytest.mark.parametrize("state", list(DatasetState))
def test_parse_dataset_state(state: DatasetState) -> None:
    assert parse_dataset_state({"status": state.value}) is state  # type: ignore[typeddict-item]


@pytest.mark.parametrize("payload", [{}, {"status": "weird"}, {"status": None}])
def test_parse_dataset_state_malformed(payload: dict[str, object]) -> None:
    with pytest.raises(RemoteError, match="malformed"):
        parse_dataset_state(payload)  # type: ignore[arg-type]


def test_state_groups_are_disjoint_where_it_matters() -> None:
    assert not set(RUNNING_DATASET_STATES) & set(NON_BLOCKING_DATASET_STATES)
    assert not set(REJECTABLE_DATASET_STATES) & set(NON_BLOCKING_DATASET_STATES)
    assert set(PROCESSABLE_DATASET_STATES) <= {DatasetState.PENDING, DatasetState.FAILED}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [(None, None), ({"status": "approved"}, DatasetState.APPROVED)],
)
def test_retrieve_dataset_state(
    mocker: MockerFixture,
    payload: dict[str, str] | None,
    expected: DatasetState | None,
) -> None:
    make_client = mocker.patch.object(dataset_status, "make_client")
    client = make_client.return_value.__enter__.return_value
    client.retrieve_dataset_or_none.return_value = payload

    assert retrieve_dataset_state(business_area_slug="afg", program_code="prog", dataset_id=DATASET_ID) == expected
    make_client.assert_called_once_with(business_area_slug="afg", program_code="prog", dataset_id=DATASET_ID)
