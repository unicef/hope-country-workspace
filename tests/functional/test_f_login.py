import pytest

pytestmark = pytest.mark.xdist_group("selenium")


@pytest.mark.selenium
def test_login(browser):
    browser.login()
    browser.assert_text("Welcome to HOPE Workspace", "div#content h1")
