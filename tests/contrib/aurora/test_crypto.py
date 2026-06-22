import json

import pytest
from cryptography.fernet import Fernet

from country_workspace.contrib.aurora.crypto import AuroraPayloadDecryptor
from country_workspace.exceptions import RemoteError


@pytest.fixture
def encryption_key() -> str:
    return Fernet.generate_key().decode("utf-8")


@pytest.fixture
def decryptor(encryption_key: str) -> AuroraPayloadDecryptor:
    return AuroraPayloadDecryptor(encryption_key)


def _make_payload(data: dict, key: str | bytes) -> str:
    json_bytes = json.dumps(data).encode("utf-8")
    token = Fernet(key).encrypt(json_bytes)
    return json.dumps({"payload": token.decode("utf-8")})


def test_decrypt_valid_payload(decryptor: AuroraPayloadDecryptor, encryption_key: str) -> None:
    original = {"results": [{"pk": 1, "fields": {"name": "Alice"}}], "count": 1, "next": None}
    envelope = _make_payload(original, encryption_key)

    result = decryptor.decrypt(envelope)

    assert result == original


def test_decrypt_round_trip_preserves_structure(decryptor: AuroraPayloadDecryptor, encryption_key: str) -> None:
    original = {
        "page": 1,
        "count": 2,
        "next": "http://example.com/api/registration/1/records/?page=2",
        "previous": None,
        "results": [{"pk": 1}, {"pk": 2}],
    }
    envelope = _make_payload(original, encryption_key)

    result = decryptor.decrypt(envelope)

    assert result["count"] == 2
    assert len(result["results"]) == 2
    assert result["next"] == original["next"]


def test_decrypt_wrong_key_raises_remote_error(encryption_key: str) -> None:
    original = {"results": [{"pk": 99}]}
    envelope = _make_payload(original, encryption_key)
    different_key = Fernet.generate_key().decode("utf-8")
    decryptor_wrong = AuroraPayloadDecryptor(different_key)

    with pytest.raises(RemoteError, match="invalid or expired key"):
        decryptor_wrong.decrypt(envelope)


def test_decrypt_tampered_ciphertext_raises_remote_error(decryptor: AuroraPayloadDecryptor) -> None:
    envelope = json.dumps({"payload": "notavalidfernettoken=="})

    with pytest.raises(RemoteError, match="invalid or expired key"):
        decryptor.decrypt(envelope)


def test_decrypt_missing_payload_key_raises_remote_error(decryptor: AuroraPayloadDecryptor) -> None:
    envelope = json.dumps({"data": "no payload field here"})

    with pytest.raises(RemoteError, match="malformed payload envelope"):
        decryptor.decrypt(envelope)


@pytest.mark.parametrize("payload_value", [None, 123, [], {}])
def test_decrypt_non_string_payload_raises_remote_error(
    decryptor: AuroraPayloadDecryptor, payload_value: object
) -> None:
    envelope = json.dumps({"payload": payload_value})

    with pytest.raises(RemoteError, match="malformed payload envelope"):
        decryptor.decrypt(envelope)


def test_decrypt_non_json_envelope_raises_remote_error(decryptor: AuroraPayloadDecryptor) -> None:
    with pytest.raises(RemoteError, match="malformed payload envelope"):
        decryptor.decrypt("this is not json at all")


def test_decrypt_logs_error_on_invalid_token(
    decryptor: AuroraPayloadDecryptor, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    envelope = json.dumps({"payload": "invaliddtoken"})
    with caplog.at_level(logging.ERROR, logger="country_workspace.contrib.aurora.crypto"):
        with pytest.raises(RemoteError):
            decryptor.decrypt(envelope)

    assert any("decryption failed" in record.message for record in caplog.records)
