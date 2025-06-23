from country_workspace.utils.functional import apply, compose
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


def test_apply() -> None:
    f: Callable[[int], int] = lambda x: x + 1
    assert apply(1, f) == f(1)


def test_compose() -> None:
    f0: Callable[[int], int] = lambda x: x + 1
    f1: Callable[[int], int] = lambda x: x * 2
    assert compose(f0, f1)(1) == f1(f0(1))
