import base64
import io
import json
import os

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from country_workspace.contrib.aurora.crypto import decrypt_payload, decrypt_record_fields

PUBLIC = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxPyACSP38j/kB9jR8QPZ
dPch3L+27c7FmzPOnA2FAI52Cfn6aiddQQyEyN6b3pXHxN+3haVIPr2yYu+4gwBC
YoUm45sMtXXtpAmQXjQoXGNGvNMsYQPWd10MHC1eSMXrxAGzqKZaTLcbrY06FIyt
nWc24+D8tHj50QEoSbIk5ex+8gtZAXi0YWmQWma4+IbpiE353wqjjvSDtyHQxnZ/
emWBBlsTJnovkD3uPLkRlQE4dIqYkLvBgRFCZm88aGBjsQXWd2goJbpfQXmatCdh
IAlFN8Uvk+muYvmHroIxVNoz496WLSfFT8f1Dr0b6+urUT2dF20Rk7M+iFm4F2wB
MQIDAQAB
-----END PUBLIC KEY-----"""

PRIVATE = b"""-----BEGIN RSA PRIVATE KEY-----
MIIEogIBAAKCAQEAxPyACSP38j/kB9jR8QPZdPch3L+27c7FmzPOnA2FAI52Cfn6
aiddQQyEyN6b3pXHxN+3haVIPr2yYu+4gwBCYoUm45sMtXXtpAmQXjQoXGNGvNMs
YQPWd10MHC1eSMXrxAGzqKZaTLcbrY06FIytnWc24+D8tHj50QEoSbIk5ex+8gtZ
AXi0YWmQWma4+IbpiE353wqjjvSDtyHQxnZ/emWBBlsTJnovkD3uPLkRlQE4dIqY
kLvBgRFCZm88aGBjsQXWd2goJbpfQXmatCdhIAlFN8Uvk+muYvmHroIxVNoz496W
LSfFT8f1Dr0b6+urUT2dF20Rk7M+iFm4F2wBMQIDAQABAoIBAAFAGQ/1yn0fKrNi
DPMasyaq6uwby213AooZqhYTf+ShAt7NV2mVFmJzUeR0hUjEaqA1S1Tt16eOTLOU
EffC6Kj3b2fCdDIyrW99IA15B0iO2MQaEw4KmDHpxUnof9C2cOitmhZX9/rErshL
PTMkMXXuUcrggroiinNpLnhJSTKsasPpMiwbypERyCl4LLBJ6T0QTyAH06CCgppM
68W6qAC5yV32OjULTDGzvdMYsFtFT0bUXRv5O09H52xMmYQneglElsdHvH4eKpA4
mquL7mX1YjnUKJ49cT/PHThlXN3Dy5gWzzrYmrewGerASw2X7VcEBzZSDp7JDLyA
T3OrQAECgYEAyemXvtxAQG+dPTsGyDnq6K55rJc9lppw1qSrroTOR06oXCrNWfDJ
0mBSqZf7cVwJZYPj1k9qCjmSJiy9p98AVx3/VtzPjJLUJwriVmhSonMQpAz1D3i2
F6F4b3EYj2VPBFAGEh8g3WT/PNv48v+9JdmA5p/u6EdXD1oIXT2fq5ECgYEA+cEX
PkQDHULQfW3v19gWI/F+CCX8B9My/c3U27Pa2I0ZZQMwFLwlwX66VCC7gD9Ty3hB
35YIT5RJwQX8xU2v7pPfFdaWSTO5fiDzBqo67r5WDfWnPCsqDpnlYmM1Kdtxu/TU
Awk0toGqMYUZNBG7fEWqHGfxRlF8eojAJyvT66ECgYALX+l4ixfjiWYmSOj85qZh
LVMVcf+6OEEbFnPFhR3JzpiVeKPQ6Uu1Wk/N1g4IONMesOto61hh8xRUqjiU+G8g
eUQlNJNMrAjfmjFeBMqC9FB/rWswz/ASLLqILKrhiSeGaqus4awMTOBEIXBI4Ddb
poEofOIMm9g/uSa3ef1AwQKBgAcI71SrqcLLPQArdpQH3CfLB5fHKiA2TLtlbtd5
a3KqFssHmfUbj5yxqyHvghiMsBmNG53mpflH3gP33TTZiVkZBTGiR71sHY918iJ/
7QUIi3f9MWa6eIbMwu9QiBDTw5JdxRMI0VlKsbaPXzReQ3+unqoKK3ulk/IHpBH2
ZBPBAoGANeGueLzJ/laKVvJ3fnkKTPw/japz/+GKyWGCjEIBSj5ucF2ktnBUA2xF
tzDrltIzCujyRRDKDIqdxOTOC/WzR+UJKz/W4MWq4ttTwvH2QiDPBsUUB7GhiMbB
btcA1UFpS9TFL++uMmwbcMzykITUTxhHp0QWEg1cpj8HFakPBZ4=
-----END RSA PRIVATE KEY-----"""


def _crypt(data: str, public_pem: bytes) -> bytes:
    payload: bytes = data.encode("utf-8")
    file_out = io.BytesIO()
    file_in = io.BytesIO(payload)

    public_key = serialization.load_pem_public_key(public_pem, backend=default_backend())
    symmetric_key = os.urandom(32)
    enc_symmetric_key = public_key.encrypt(
        symmetric_key, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    )
    file_out.write(enc_symmetric_key)

    while True:
        data_chunk = file_in.read(1024)
        if data_chunk:
            iv = os.urandom(16)
            cipher = Cipher(algorithms.AES(symmetric_key), modes.GCM(iv), backend=default_backend())
            encryptor = cipher.encryptor()
            ciphertext = encryptor.update(data_chunk) + encryptor.finalize()
            file_out.write(iv + encryptor.tag + ciphertext)
        else:
            break

    file_out.seek(0)
    return file_out.read()


def _encrypt_fields(fields: dict) -> str:
    encrypted = _crypt(json.dumps(fields), PUBLIC)
    return base64.b64encode(encrypted).decode()


def test_decrypt_record_fields_roundtrip() -> None:
    fields = {"first_name": "Alice", "last_name": "Smith"}
    encrypted_fields = _encrypt_fields(fields)

    assert decrypt_record_fields(encrypted_fields, PRIVATE.decode()) == fields


@pytest.mark.parametrize(
    "payload",
    [
        {"given_name_i_c": "Alice", "family_name_i_c": "Green"},
        {"individual-details": [{"given_name_i_c": "Bruno"}]},
    ],
)
def test_decrypt_record_fields_various_payloads(payload: dict) -> None:
    encrypted_fields = _encrypt_fields(payload)
    assert decrypt_record_fields(encrypted_fields, PRIVATE.decode()) == payload


# --- decrypt_payload ---------------------------------------------------------------


def test_decrypt_payload_merges_decrypted_fields_and_files() -> None:
    fields = {"given_name_i_c": "Alice", "family_name_i_c": "Green"}
    files = {"attachment_i_c": "photo.jpg"}
    payload = {
        "encryption": "rsa",
        "fields": _encrypt_fields(fields),
        "files": _encrypt_fields(files),
    }

    assert decrypt_payload(payload, PRIVATE.decode()) == {**files, **fields}


def test_decrypt_payload_treats_empty_files_as_no_op() -> None:
    fields = {"given_name_i_c": "Alice"}
    payload = {
        "encryption": "rsa",
        "fields": _encrypt_fields(fields),
        "files": "",
    }

    assert decrypt_payload(payload, PRIVATE.decode()) == fields


def test_decrypt_payload_treats_missing_files_as_no_op() -> None:
    fields = {"given_name_i_c": "Alice"}
    payload = {
        "encryption": "rsa",
        "fields": _encrypt_fields(fields),
    }

    assert decrypt_payload(payload, PRIVATE.decode()) == fields


def test_decrypt_payload_rejects_unsupported_encryption_scheme() -> None:
    payload = {"encryption": "pgp", "fields": "", "files": ""}

    with pytest.raises(ValueError, match="Unsupported Aurora encryption scheme"):
        decrypt_payload(payload, PRIVATE.decode())
