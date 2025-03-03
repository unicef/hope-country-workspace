from collections.abc import Callable

from requests import Response

DataGetter = Callable[[str], Response]
