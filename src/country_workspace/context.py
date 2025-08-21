from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_CTX_BATCH: ContextVar[int | None] = ContextVar("_CTX_BATCH", default=None)


def set_batch(batch_id: int | None) -> Token:
    return _CTX_BATCH.set(batch_id)


def get_batch() -> int | None:
    return _CTX_BATCH.get()


def reset_batch(token: Token) -> None:
    _CTX_BATCH.reset(token)


@contextmanager
def batch_ctx(batch_id: int | None) -> Generator[None, None, None]:
    token = set_batch(batch_id)
    try:
        yield
    finally:
        reset_batch(token)
