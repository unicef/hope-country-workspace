from functools import partial

KOBO_SYNC_LOG_PREFIX = "kobo"
AURORA_SYNC_LOG_PREFIX = "aurora"


def get_sync_log_name(prefix: str, asset_uid: str) -> str:
    return f"{prefix}_{asset_uid}"


get_kobo_sync_log_name = partial(get_sync_log_name, KOBO_SYNC_LOG_PREFIX)
get_aurora_sync_log_name = partial(get_sync_log_name, AURORA_SYNC_LOG_PREFIX)
