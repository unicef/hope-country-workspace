from country_workspace.config.celery import app, init_sentry
from country_workspace.tasks import removed_expired_jobs


def test_celery_app(**kwargs):
    app.autodiscover_tasks()
    assert True


def test_celery_init_sentry(**kwargs):
    init_sentry()
    assert True


def test_removed_expired_jobs(**kwargs):
    removed_expired_jobs()
