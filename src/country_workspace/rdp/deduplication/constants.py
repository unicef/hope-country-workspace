from typing import Final


DEDUP_CALLBACK_MAX_AGE: Final[int] = 60 * 60 * 96  # 96 hours
DEDUP_CALLBACK_SALT: Final[str] = "country_workspace.deduplication.callback"
