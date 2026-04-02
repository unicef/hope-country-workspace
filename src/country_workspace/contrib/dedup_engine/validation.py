from collections.abc import Mapping

from country_workspace.exceptions import RemoteError


def _malformed(operation: str) -> RemoteError:
    return RemoteError(f"DedupEngine: {operation} failed: malformed JSON response")


def expect_mapping(payload: object, operation: str) -> Mapping[str, object]:
    if isinstance(payload, Mapping):
        return payload
    raise _malformed(operation)


def get_required_bool(payload: Mapping[str, object], key: str, operation: str) -> bool:
    if isinstance((value := payload.get(key)), bool):
        return value
    raise _malformed(operation)


def get_optional_str(payload: Mapping[str, object], key: str) -> str | None:
    if isinstance((value := payload.get(key)), str):
        return value
    return None


def get_optional_int(payload: Mapping[str, object], key: str, default: int = -1) -> int:
    if type(value := payload.get(key)) is int:
        return value
    return default
