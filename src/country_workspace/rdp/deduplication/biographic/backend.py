from country_workspace.models import RdpOperation

from ..backend import DeduplicationBackend
from .actions import approve_biographic_dataset_after_successful_push
from .lifecycle import check_biographic_cancellation, check_biographic_clean, reject_cancelled_biographic_dataset
from .workflow import sync_biographic_result


BIOGRAPHIC_BACKEND = DeduplicationBackend(
    operation_type=RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION,
    sync=sync_biographic_result,
    check_cancellation=check_biographic_cancellation,
    check_clean=check_biographic_clean,
    reject=reject_cancelled_biographic_dataset,
    approve=approve_biographic_dataset_after_successful_push,
)
