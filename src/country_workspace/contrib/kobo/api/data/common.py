class Raw[T]:
    def __init__(self, raw: T) -> None:
        self._raw = raw

    @property
    def raw(self) -> T:
        return self._raw
