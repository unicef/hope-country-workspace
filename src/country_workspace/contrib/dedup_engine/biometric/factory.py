from collections.abc import Generator
from contextlib import contextmanager

from constance import config

from ..factory import make_session
from .client import Client
from .endpoint import APIRoot


@contextmanager
def make_client(
    group_reference_id: str,
    deduplication_set_id: str | None = None,
    *,
    max_retries: int = 3,
) -> Generator[Client, None, None]:
    with make_session(max_retries=max_retries) as session:
        yield Client(
            group_reference_id=group_reference_id,
            session=session,
            api_root=APIRoot(config.DEDUP_API_URL),
            deduplication_set_id=deduplication_set_id,
        )
