import contextlib
import json
from pathlib import Path
from unittest.mock import Mock


def payload(filename, section=None):
    data = json.load((Path(__file__).parent / filename).open())
    if section:
        return data[section]
    return data


def get_all_attributes(driver, element):
    return list(
        driver.execute_script(
            "var items = {}; for (index = 0; index < arguments[0].attributes.length; ++index) {"
            " items[arguments[0].attributes[index].name] = arguments[0].attributes[index].value"
            " }; return items;",
            element,
        )
    )


def mykey(group, request):
    return request.META["REMOTE_ADDR"][::-1]


def callable_rate(group, request):
    if request.user.is_authenticated:
        return None
    return (0, 1)


@contextlib.contextmanager
def set_flag(flag_name, on_off):
    from flags.state import _set_flag_state, flag_state

    state = flag_state(flag_name)
    _set_flag_state(flag_name, on_off)
    yield
    _set_flag_state(flag_name, state)


@contextlib.contextmanager
def select_office(app, country_office, program=None):
    res = app.get("/+st/")
    res.forms["select-tenant"]["tenant"] = country_office.pk
    res = res.forms["select-tenant"].submit()
    if program:
        res = app.get("/")
        res.forms["select-program"]["program"].force_value(program.pk)
        res.forms["select-program"].submit()
    yield


def assert_stdout_contains(out: Mock, *patterns: str, not_contains: list[str] | None = None) -> None:
    calls = [call[0][0] for call in out.write.call_args_list]
    for pattern in patterns:
        assert any(pattern in c for c in calls), f"Expected '{pattern}' not in stdout"
    if not_contains:
        for pattern in not_contains:
            assert not any(pattern in c for c in calls), f"Unexpected '{pattern}' in stdout"
