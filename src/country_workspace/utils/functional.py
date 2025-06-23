from collections.abc import Callable
from functools import reduce, partial
from typing import overload, Any

type Function[T, R] = Callable[[T], R]


def apply[T, R](obj: T, func: Function[T, R]) -> R:
    return func(obj)


@overload
def compose[T, R](func0: Function[T, R], /) -> Function[T, R]: ...


@overload
def compose[T, TR0, R](func0: Function[T, TR0], func1: Function[TR0, T], /) -> Function[T, R]: ...


@overload
def compose[T, TR0, TR1, R](
    func0: Function[T, TR0], func1: Function[TR0, TR1], func2: Function[TR1, R], /
) -> Function[T, R]: ...


def compose(*funcs: Function[Any, Any]) -> Function[Any, Any]:
    return partial(reduce, apply, funcs)
