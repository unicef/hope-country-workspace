from typing import Dict, TYPE_CHECKING

import contextlib
from copy import copy
from threading import local

if TYPE_CHECKING:
    from typing import Any, List

    from collections.abc import Iterator

    from hope_country_report.apps.core.models import CountryOffice
    from hope_country_report.types.http import AnyRequest, AnyResponse

not_set = object()


class State(local):
    request: "AnyRequest|None" = None
    tenant_cookie: "str|None" = None
    tenant: "CountryOffice|None" = None
    must_tenant: "bool|None" = None
    cookies: "dict[str, List[Any]]" = {}
    filters: "List[Any]" = []
    inspecting: bool = False

    def __repr__(self) -> str:
        return f"<State {id(self)}: {self.tenant_cookie}:{self.must_tenant}>"

    @contextlib.contextmanager
    def configure(self, **kwargs: "Dict[str,Any]") -> "Iterator[None]":
        pre = copy(self.__dict__)
        self.reset()
        with self.set(**kwargs):
            yield
        for k, v in pre.items():
            setattr(self, k, v)

    @contextlib.contextmanager
    def activate_tenant(self, country_office: "CountryOffice") -> "Iterator[None]":
        _must_tenant = self.must_tenant
        _country_office = self.tenant
        _tenant_cookie = self.tenant_cookie
        self.must_tenant = True
        self.tenant = country_office
        self.tenant_cookie = country_office.slug
        yield
        self.must_tenant = _must_tenant
        self.tenant = _country_office
        self.tenant_cookie = _tenant_cookie

    @contextlib.contextmanager
    def set(self, **kwargs: "Dict[str,Any]") -> "Iterator[None]":
        pre = {}
        for k, v in kwargs.items():
            if hasattr(self, k):
                pre[k] = getattr(self, k)
            else:
                pre[k] = not_set
            setattr(self, k, v)
        yield
        for k, v in pre.items():
            if v is not_set:
                delattr(self, k)
            else:
                setattr(self, k, v)

    def add_cookies(
        self,
        key: str,
        value: str,
        max_age: "int|None" = None,
        expires: "int|None" = None,
        path: str = "/",
        domain: str | None = None,
        secure: bool = False,
        httponly: bool = False,
        samesite: "Any" = None,
    ) -> None:
        self.cookies[key] = [value, max_age, expires, path, domain, secure, httponly, samesite]

    def set_cookies(self, response: "AnyResponse") -> None:
        for name, args in self.cookies.items():
            response.set_cookie(name, *args)

    def reset(self) -> None:
        self.tenant = None
        self.tenant_cookie = None
        self.must_tenant = None
        self.request = None
        self.cookies = {}
        self.filters = []
        self.inspecting = False


state = State()
