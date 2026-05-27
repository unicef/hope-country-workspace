from collections.abc import Generator
from contextlib import contextmanager

from constance import config
from requests import Session
from requests.adapters import HTTPAdapter

from country_workspace.utils.auth import Auth
from .endpoint import APIRoot
from .client import Client


@contextmanager
def make_client(
    group_reference_id: str,
    deduplication_set_id: str | None = None,
) -> Generator[Client, None, None]:
    with Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=3))
        session.mount("http://", HTTPAdapter(max_retries=3))
        session.auth = Auth(config.DEDUP_API_TOKEN)
        api_root = APIRoot(config.DEDUP_API_URL)
        yield Client(
            group_reference_id=group_reference_id,
            session=session,
            api_root=api_root,
            deduplication_set_id=deduplication_set_id,
        )
