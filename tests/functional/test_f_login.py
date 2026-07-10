import pytest
from django.test import override_settings

pytestmark = pytest.mark.xdist_group("selenium")


@override_settings(LOGIN_ENABLED=True)
@pytest.mark.selenium
def test_admin_login(browser):
    browser.login()
    browser.assert_text("Welcome to HOPE Workspace", "div#content h1")


@override_settings(LOGIN_ENABLED=True)
@pytest.mark.selenium
def test_logout(browser):
    browser.login()
    browser.assert_text("Welcome to HOPE Workspace", "div#content h1")
    browser.click('form[action="/admin/logout/"] button')
    browser.assert_url(f"{browser.live_server_url}/login/")
    browser.assert_text("HOPE Workspace", "div.text-5xl")


@pytest.mark.selenium
def test_user_login(browser, user, settings):
    browser.login_as_user(user)
    browser.assert_text("You do not have any Office enabled.")
