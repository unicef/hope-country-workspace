import pytest

pytestmark = pytest.mark.xdist_group("selenium")


@pytest.mark.selenium
def test_login(browser):
    # Not sure if this makes any sense
    browser.login()
