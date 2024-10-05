import contextlib
import json
from pathlib import Path

from django.urls import reverse


def payload(filename, section=None):
    data = json.load((Path(__file__).parent / filename).open())
    if section:
        return data[section]
    return data


def check_link_by_class(selenium, cls, view_name):
    link = selenium.find_element_by_class_name(cls)
    url = reverse(f"{view_name}")
    return f' href="{url}"' in link.get_attribute("innerHTML")


def get_all_attributes(driver, element):
    return list(
        driver.execute_script(
            "var items = {}; for (index = 0; index < arguments[0].attributes.length; ++index) {"
            " items[arguments[0].attributes[index].name] = arguments[0].attributes[index].value"
            " }; return items;",
            element,
        )
    )


def is_clickable(driver, element):
    """Tries to click the element"""
    try:
        element.click()
        return True
    except Exception:
        return False


def mykey(group, request):
    return request.META["REMOTE_ADDR"][::-1]


def callable_rate(group, request):
    if request.user.is_authenticated:
        return None
    return (0, 1)


def wait_for(driver, *args):
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    wait = WebDriverWait(driver, 10)
    wait.until(EC.visibility_of_element_located((*args,)))
    return driver.find_element(*args)


def wait_for_url(driver, url):
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    wait = WebDriverWait(driver, 10)
    wait.until(EC.url_contains(url))


@contextlib.contextmanager
def set_flag(flag_name, on_off):
    from flags.state import _set_flag_state, flag_state

    state = flag_state(flag_name)
    _set_flag_state(flag_name, on_off)
    yield
    _set_flag_state(flag_name, state)


def force_login(user, driver, base_url):
    from importlib import import_module

    from django.conf import settings
    from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY

    SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
    # selenium_login_start_page = getattr(settings, 'SELENIUM_LOGIN_START_PAGE', '/')
    # driver.get('{}{}'.format(base_url, selenium_login_start_page))
    with driver.with_timeouts(page=5):
        driver.get(base_url)

    session = SessionStore()
    session[SESSION_KEY] = user._meta.pk.value_to_string(user)
    session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session.save()

    driver.add_cookie(
        {
            "name": settings.SESSION_COOKIE_NAME,
            "value": session.session_key,
            "path": "/",
        }
    )
    driver.add_cookie(
        {
            "name": "gdpr",
            "value": '{"base":1, "set":1, "optionals": 1}',
            "secure": False,
            "path": "/",
        }
    )
    driver.refresh()
