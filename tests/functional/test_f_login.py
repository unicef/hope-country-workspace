import pytest


@pytest.mark.selenium
def test_login(live_server, selenium, user):
    selenium.get(f"{live_server.url}")
    selenium.find_by_css("input[name=username").send_keys(user.username)
    selenium.find_by_css("input[name=password").send_keys(user._password)
    selenium.find_by_css("input[type=submit").click()

    assert "Seems you do not have any tenant enabled." in selenium.page_source
