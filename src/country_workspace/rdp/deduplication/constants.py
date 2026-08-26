from typing import Final

DEDUP_CALLBACK_MAX_AGE: Final[int] = 60 * 60 * 96  # 96 hours
DEDUP_CALLBACK_SALT: Final[str] = "dedup_callback"

IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE: Final[int] = 10
