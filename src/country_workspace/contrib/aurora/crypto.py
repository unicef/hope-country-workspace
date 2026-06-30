import base64
import io
import json
import logging
from typing import Any

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
