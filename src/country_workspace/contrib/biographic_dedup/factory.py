from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from constance import config
from requests import Session
from requests.adapters import HTTPAdapter

from country_workspace.exceptions import RemoteError
from country_workspace.utils.auth import Auth

from country_workspace.contrib.dedup_engine.endpoint import url_join

from .client import BiographicClient

BIOGRAPHIC_API_PATH = "api/biographic"

if TYPE_CHECKING:
    from country_workspace.models import Program


def program_route(program: "Program") -> tuple[str, str]:
    """Return the business area slug and program code that address the program in DedupEngine."""
    business_area = getattr(program.country_office, "slug", None)
    if not business_area or not program.code:
        raise RemoteError("Biographic DedupEngine: program requires country_office.slug and code.")
    return business_area, program.code


@contextmanager
def make_client(
    program: "Program",
    dataset_id: int | str | None = None,
    *,
    max_retries: int = 3,
) -> Generator[BiographicClient, None, None]:
    """Open a client for the program's biographic sets, optionally bound to one of them.

    The biographic API lives on the same DedupEngine as the biometric one, so it shares its URL and token.
    """
    if not (config.DEDUP_API_URL and config.DEDUP_API_TOKEN):
        raise RemoteError("Biographic DedupEngine is not configured.")

    business_area, program_code = program_route(program)
    with Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=max_retries))
        session.mount("http://", HTTPAdapter(max_retries=max_retries))
        session.auth = Auth(config.DEDUP_API_TOKEN)
        yield BiographicClient(
            session=session,
            base_url=url_join(config.DEDUP_API_URL, BIOGRAPHIC_API_PATH),
            business_area=business_area,
            program_code=program_code,
            dataset_id=int(dataset_id) if dataset_id not in (None, "") else None,
        )
