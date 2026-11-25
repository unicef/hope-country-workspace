from collections.abc import Generator
from contextlib import contextmanager

from constance import config
from requests import Session
from requests.adapters import HTTPAdapter

from country_workspace.utils.auth import Auth


@contextmanager
def make_session(*, max_retries: int = 3) -> Generator[Session, None, None]:
    with Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=max_retries))
        session.mount("http://", HTTPAdapter(max_retries=max_retries))
        session.auth = Auth(config.DEDUP_API_TOKEN)
        yield session
