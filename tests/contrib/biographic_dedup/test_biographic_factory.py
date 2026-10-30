import pytest
from constance.test import override_config
from pytest_mock import MockerFixture

from country_workspace.contrib.biographic_dedup import factory, state
from country_workspace.contrib.biographic_dedup.schemas import BiographicSetState
from country_workspace.exceptions import RemoteError


@pytest.fixture
def program():
    from testutils.factories import ProgramFactory

    return ProgramFactory(code="PRG")


def test_program_route(program) -> None:
    assert factory.program_route(program) == (program.country_office.slug, "PRG")


def test_program_route_requires_code(program) -> None:
    program.code = ""

    with pytest.raises(RemoteError):
        factory.program_route(program)


@pytest.mark.parametrize(
    "settings",
    [{"DEDUP_API_URL": "", "DEDUP_API_TOKEN": "t"}, {"DEDUP_API_URL": "https://de", "DEDUP_API_TOKEN": ""}],
)
def test_make_client_requires_configuration(program, settings: dict[str, str]) -> None:
    with override_config(**settings):
        with pytest.raises(RemoteError, match="not configured"):
            with factory.make_client(program):
                pass


@pytest.mark.parametrize(("dataset_id", "expected"), [(None, None), ("", None), ("12", 12), (12, 12)])
def test_make_client(program, dataset_id: object, expected: int | None) -> None:
    with override_config(DEDUP_API_URL="https://de", DEDUP_API_TOKEN="tok"):
        with factory.make_client(program, dataset_id=dataset_id) as client:  # type: ignore[arg-type]
            assert client.dataset_id == expected
            assert client.business_area == program.country_office.slug
            assert client.program_code == "PRG"
            assert client.datasets_url == f"https://de/api/biographic/{program.country_office.slug}/PRG/datasets/"
            assert client.session.auth is not None
            assert client.session.auth(type("R", (), {"headers": {}})()).headers["Authorization"] == "Token tok"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"status": "deduplicated"}, BiographicSetState.DEDUPLICATED),
        ({"status": "pending"}, BiographicSetState.PENDING),
    ],
)
def test_parse_set_state(payload: dict[str, str], expected: BiographicSetState) -> None:
    assert state.parse_set_state(payload) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("payload", [{}, {"status": "weird"}, {"status": None}])
def test_parse_set_state_malformed(payload: dict[str, object]) -> None:
    with pytest.raises(RemoteError, match="malformed"):
        state.parse_set_state(payload)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [(None, None), ({"status": "approved"}, BiographicSetState.APPROVED)],
)
def test_retrieve_biographic_set_state(
    mocker: MockerFixture,
    program,
    payload: dict[str, str] | None,
    expected: BiographicSetState | None,
) -> None:
    make_client = mocker.patch.object(state, "make_client")
    client = make_client.return_value.__enter__.return_value
    client.retrieve_dataset_or_none.return_value = payload

    assert state.retrieve_biographic_set_state(program, 5) == expected
    make_client.assert_called_once_with(program, dataset_id=5)
