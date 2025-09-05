# this import is required for django_celery_results to have access to the
# configured Celery application. without it, it's possible that
# celery.current_app will be set to a newly created application with the default
# configuration
from country_workspace.config.celery import app  # noqa: F401
