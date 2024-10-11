def force_login(driver, user, tenant=None):
    from importlib import import_module

    from django.conf import settings
    from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY

    SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
    with driver.with_timeouts(page=10):
        driver.get(driver.live_server.url)

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
    driver.refresh()
    if tenant:
        from django.core.signing import get_cookie_signer

        from country_workspace.workspaces.config import conf
        from country_workspace.workspaces.utils import set_selected_tenant

        signer = get_cookie_signer()
        driver.add_cookie(
            {
                "name": conf.COOKIE_NAME,
                "value": signer.sign(tenant.slug),
                "secure": False,
                "path": "/",
            }
        )
        set_selected_tenant(tenant)
