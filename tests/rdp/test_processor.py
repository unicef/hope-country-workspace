import pytest
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.rdp.processor import ERROR_CONFIG, ProcessorBase


@pytest.fixture
def processor() -> ProcessorBase:
    return ProcessorBase()


@pytest.mark.parametrize(
    "case",
    [
        ([], "[]"),
        ([1, 2], "[1, 2]"),
        ([1, 2, 3, 4, 5, 6], "[1, 2, 3, 4, 5, …]"),
    ],
    ids=["empty", "short", "truncated"],
)
def test_ids_hint(case) -> None:
    ids, expected = case

    assert ProcessorBase._ids_hint(ids) == expected


@pytest.mark.parametrize(
    "case",
    [
        ("message", ["message"]),
        ("x" * (ERROR_CONFIG.MAX_ERROR_LEN + 1), ["x" * (ERROR_CONFIG.MAX_ERROR_LEN - 1) + "…"]),
    ],
    ids=["normal", "truncated"],
)
def test_err(processor: ProcessorBase, case) -> None:
    message, expected = case

    processor._err(message)

    assert processor.total["errors"] == expected


def test_err_caps_errors(processor: ProcessorBase) -> None:
    processor.total["errors"] = ["error"] * (ERROR_CONFIG.MAX_ERRORS - 1)

    processor._err("last")
    processor._err("ignored")

    assert processor.total["errors"][-1] == ERROR_CONFIG.MARKER
    assert len(processor.total["errors"]) == ERROR_CONFIG.MAX_ERRORS


@pytest.mark.parametrize(
    "case",
    [
        (None, None, "Processor: subject: message"),
        ([1, 2], None, "Processor: subject: message ids=[1, 2]"),
        (None, {"error": "bad"}, "Processor: subject: message. Response: {'error': 'bad'}"),
    ],
    ids=["plain", "ids", "response"],
)
def test_fail(processor: ProcessorBase, case) -> None:
    ids, response, expected = case

    processor.fail("subject", "message", ids=ids, response=response)

    assert processor.total["errors"] == [expected]
    assert processor.has_errors is True


@pytest.mark.parametrize(
    "method",
    ["try_remote", "run_remote"],
    ids=["try", "run"],
)
def test_remote_success(processor: ProcessorBase, mocker: MockerFixture, method: str) -> None:
    fn = mocker.Mock(return_value="result")

    result = getattr(processor, method)("subject", fn, ids=[1])

    assert result == ("result" if method == "try_remote" else True)
    assert processor.has_errors is False


@pytest.mark.parametrize(
    "case",
    [
        ("try_remote", RemoteError("boom"), None),
        ("try_remote", RemoteUnavailableError("boom"), None),
        ("run_remote", RemoteError("boom"), False),
        ("run_remote", RemoteUnavailableError("boom"), False),
    ],
    ids=["try_remote", "try_unavailable", "run_remote", "run_unavailable"],
)
def test_remote_failure(processor: ProcessorBase, mocker: MockerFixture, case) -> None:
    method, error, expected = case
    fn = mocker.Mock(side_effect=error)

    assert getattr(processor, method)("subject", fn, ids=[1, 2]) is expected
    assert processor.total["errors"] == ["Processor: subject: request failed. boom ids=[1, 2]"]
