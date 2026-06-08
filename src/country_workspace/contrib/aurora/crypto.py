import json
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from country_workspace.exceptions import RemoteError

logger = logging.getLogger(__name__)

ENCRYPTED_CONTENT_TYPE = "application/encrypted+json"


class AuroraPayloadDecryptor:
    """
    Decrypts Fernet-encrypted response payloads from the Aurora API.

    This is the counterpart to Aurora's ``EncryptedJSONRenderer``. The expected
    wire format received from Aurora is a JSON object with a single field::

        Content-Type: application/encrypted+json
        {"payload": "<fernet_token>"}

    The ``fernet_token`` is a URL-safe base64-encoded Fernet ciphertext. It is
    decrypted using the pre-shared ``AURORA_PAYLOAD_ENCRYPTION_KEY`` (the same
    key configured on the Aurora side). The key is never transmitted.

    Key generation (run once, deploy to both systems as AURORA_PAYLOAD_ENCRYPTION_KEY)::

        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    """

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key)

    def decrypt(self, response_text: str) -> Any:
        """
        Decrypt a Fernet-encrypted Aurora API response body.

        Args:
            response_text: The raw response body string (JSON envelope).

        Returns:
            The deserialized Python object from the decrypted payload.

        Raises:
            RemoteError: If decryption fails due to an invalid/expired key,
                         or if the response structure is malformed.

        """
        try:
            outer = json.loads(response_text)
            token: str = outer["payload"]
            plaintext: bytes = self._fernet.decrypt(token.encode("utf-8"))
            return json.loads(plaintext)
        except InvalidToken as exc:
            logger.error("Aurora payload decryption failed: invalid or expired key. %s", exc)
            raise RemoteError("Failed to decrypt Aurora response: invalid or expired key") from exc
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("Aurora payload decryption failed: malformed response envelope. %s", exc)
            raise RemoteError("Failed to decrypt Aurora response: malformed payload envelope") from exc
