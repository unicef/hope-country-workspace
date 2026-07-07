import base64
import io
import json
import logging
from typing import Any, Mapping

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)


def decrypt(data: bytes, private_pem: str) -> str:
    file_in = io.BytesIO(data)
    file_out = io.BytesIO()

    private_key = serialization.load_pem_private_key(private_pem.encode(), password=None, backend=default_backend())
    enc_key_size = private_key.key_size // 8
    enc_symmetric_key = file_in.read(enc_key_size)
    symmetric_key = private_key.decrypt(
        enc_symmetric_key,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )

    while True:
        iv = file_in.read(16)
        if not iv:
            break
        tag = file_in.read(16)
        ciphertxt_tag = file_in.read(1024)
        cipher = Cipher(algorithms.AES(symmetric_key), modes.GCM(iv, tag), backend=default_backend())
        decryptor = cipher.decryptor()
        file_out.write(decryptor.update(ciphertxt_tag) + decryptor.finalize())

    file_out.seek(0)
    return file_out.read().decode()


def decrypt_record_fields(encrypted_fields: str, private_key_pem: str) -> dict[str, Any]:
    plaintext = decrypt(base64.b64decode(encrypted_fields), private_key_pem)
    return json.loads(plaintext)


def merge(a: dict, b: dict, path: list[str] | None = None, update: bool = True) -> dict[str, Any]:
    """Merge ``b`` into ``a``.

    Direct port of ``aurora.registration.models.merge`` so that records decrypted from
    Aurora's ``ser=encrypted`` payload end up shaped exactly like Aurora's own pre-merged
    ``ser=full`` ``data``.
    """
    if path is None:
        path = []
    for key, value in b.items():
        if key in a:
            if isinstance(a[key], dict) and isinstance(value, dict):
                merge(a[key], value, path + [str(key)])
            elif a[key] == value:
                pass  # same leaf value
            elif isinstance(a[key], list) and isinstance(value, list):
                for idx, _ in enumerate(value):
                    a[key][idx] = merge(
                        a[key][idx],
                        value[idx],
                        path + [str(key), str(idx)],
                        update=update,
                    )
            elif update:
                a[key] = value
            else:
                msg = "Conflict at %s" % ".".join(path + [str(key)])
                raise ValueError(msg)
        else:
            a[key] = value
    return a


def _decrypt_payload_part(encoded_value: str | None, private_key_pem: str) -> dict[str, Any]:
    if not encoded_value:
        return {}
    plaintext = decrypt(base64.b64decode(encoded_value), private_key_pem)
    return json.loads(plaintext)


def decrypt_payload(payload: Mapping[str, Any], private_key_pem: str) -> dict[str, Any]:
    """Decrypt an Aurora ``ser=encrypted`` ``payload`` object into a merged plaintext dict.

    ``payload`` is expected to look like ``{"encryption": "rsa", "fields": "<base64>", "files":
    "<base64 or "">"}``. Both ``fields`` and ``files`` are decrypted independently and then
    merged the same way Aurora merges them server-side for its ``ser=full`` ``data`` property.
    """
    encryption = payload.get("encryption")
    if encryption != "rsa":
        msg = f"Unsupported Aurora encryption scheme: {encryption!r}"
        raise ValueError(msg)
    fields = _decrypt_payload_part(payload.get("fields"), private_key_pem)
    files = _decrypt_payload_part(payload.get("files"), private_key_pem)
    return merge(files, fields)
