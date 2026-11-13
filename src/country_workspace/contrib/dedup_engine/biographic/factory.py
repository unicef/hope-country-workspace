from collections.abc import Generator
from contextlib import contextmanager
from uuid import UUID

from constance import config

from ..factory import make_session
from .client import Client
from .endpoint import APIRoot


@contextmanager
def make_client(
    *,
    business_area_slug: str,
    program_code: str,
    dataset_id: UUID | str,
    max_retries: int = 3,
) -> Generator[Client, None, None]:
    with make_session(max_retries=max_retries) as session:
        yield Client(
            business_area_slug=business_area_slug,
            program_code=program_code,
            session=session,
            api_root=APIRoot(config.DEDUP_API_URL),
            dataset_id=str(dataset_id),
        )
