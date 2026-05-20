from celery.schedules import crontab

DEFAULT_QUEUE = "queue_hcw"

TASKS_SCHEDULES: dict[str, dict] = {
    "sync-hope-data-hourly": {
        "task": "country_workspace.tasks.sync_hope_data",
        "schedule": crontab(minute="0"),
        "options": {"queue": DEFAULT_QUEUE},
    },
}
