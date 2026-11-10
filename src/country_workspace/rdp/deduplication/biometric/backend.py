from country_workspace.models import RdpOperation

from ..backend import DeduplicationBackend
from .lifecycle import approve_biometric_set, check_biometric_cancellation, check_biometric_clean, reject_biometric_set
from .workflow import sync_biometric_result


BIOMETRIC_BACKEND = DeduplicationBackend(
    operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
    sync=sync_biometric_result,
    check_cancellation=check_biometric_cancellation,
    check_clean=check_biometric_clean,
    reject=reject_biometric_set,
    approve=approve_biometric_set,
)
