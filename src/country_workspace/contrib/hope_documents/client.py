import re
from base64 import b64decode
from dataclasses import dataclass
from typing import Any, Final

import requests
from constance import config
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError as RequestsConnectionError, HTTPError, RequestException

from country_workspace.exceptions import RemoteError, RemoteUnavailableError

TIMEOUTS: Final[tuple[int, int]] = (10, 30)
UPLOAD_PATH: Final[str] = "/api/upload/"
DATA_URI_RE = re.compile(r"^data:(?P<mimetype>[^;]+);base64,(?P<data>.+)$", re.DOTALL)


def decode_data_uri(data_uri: str) -> tuple[bytes, str]:
    """Decode a ``data:<mimetype>;base64,<content>`` string.

    Returns ``(raw_bytes, mimetype)``.
    """
    match = DATA_URI_RE.match(data_uri)
    if not match:
        raise ValueError("Invalid data URI format")
    return b64decode(match.group("data")), match.group("mimetype")


@dataclass(frozen=True, slots=True)
class OcrParams:
    threshold: int = 128
    mode: int = 2
    rotate: int = 0
    number_only: bool = False
    psm: int = 11
    oem: int = 3


_DEFAULT_OCR_PARAMS = OcrParams()


class HopeDocumentsClient:
    def __init__(self, *, token: str | None = None, api_url: str | None = None) -> None:
        self.api_url = (api_url or config.HOPE_DOCUMENTS_API_URL).rstrip("/")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Token {token or config.HOPE_DOCUMENTS_API_TOKEN}"
        for scheme in ("http://", "https://"):
            self.session.mount(scheme, HTTPAdapter(max_retries=3))

    def upload(
        self,
        file_content: bytes,
        filename: str,
        *,
        content_type: str = "image/png",
        pattern: str = "",
        params: OcrParams = _DEFAULT_OCR_PARAMS,
    ) -> dict[str, Any]:
        """POST a file to the hope-documents ``/api/upload/`` endpoint.

        When *pattern* is empty a full OCR extraction is performed.
        When *pattern* is provided a pattern-search is performed.
        All OCR tuning parameters are always sent explicitly to pin
        behavior regardless of server-side default changes.
        """
        url = f"{self.api_url}{UPLOAD_PATH}"
        files = {"attachment": (filename, file_content, content_type)}
        data: dict[str, Any] = {
            "threshold": params.threshold,
            "mode": params.mode,
            "rotate": params.rotate,
            "number_only": str(params.number_only).lower(),
            "psm": params.psm,
            "oem": params.oem,
        }
        if pattern:
            data["pattern"] = pattern
        try:
            response = self.session.post(url, files=files, data=data, timeout=TIMEOUTS)
            response.raise_for_status()
            return response.json()
        except RequestsConnectionError as exc:
            raise RemoteUnavailableError(f"Hope Documents service unreachable: {exc}") from exc
        except HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            raise RemoteError(f"Hope Documents API error (HTTP {status}): {exc}") from exc
        except RequestException as exc:
            raise RemoteUnavailableError(f"Hope Documents request failed: {exc}") from exc
        except ValueError as exc:
            raise RemoteError(f"Hope Documents returned invalid JSON: {exc}") from exc

    def check_document(
        self,
        image_data_uri: str,
        pattern: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Check whether *pattern* appears in the document image.

        *image_data_uri* is a ``data:<mime>;base64,…`` string as stored in
        ``Individual.flex_fields``.

        Returns a dict with at least ``found`` (bool), ``match``, and
        ``text`` keys taken from the first finding.
        """
        file_bytes, mimetype = decode_data_uri(image_data_uri)
        ext = mimetype.split("/")[-1]
        filename = f"document.{ext}"

        result = self.upload(
            file_bytes,
            filename,
            content_type=mimetype,
            pattern=pattern,
            **kwargs,
        )

        findings = result.get("findings", [])
        if not findings:
            return {"found": False, "match": None, "text": ""}

        first = findings[0]
        return {
            "found": first.get("found", False),
            "match": first.get("match"),
            "text": first.get("text", ""),
        }
