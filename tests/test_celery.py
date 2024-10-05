from country_workspace.config.celery import app, init_sentry


def test_celery_app(**kwargs):
    app.autodiscover_tasks()
    assert True


def test_celery_init_sentry(**kwargs):
    init_sentry()
    assert True
