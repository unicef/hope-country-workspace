from country_workspace.models import RdpOperation
from country_workspace.rdp.deduplication.biographic.backend import BIOGRAPHIC_BACKEND
from country_workspace.rdp.deduplication.biographic.forms import BiographicDeduplicationConfigForm
from country_workspace.rdp.forms import ThresholdConfigForm


def test_biographic_backend_operation_type() -> None:
    assert BIOGRAPHIC_BACKEND.operation_type == RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION


def test_biographic_config_form_is_threshold_form() -> None:
    assert issubclass(BiographicDeduplicationConfigForm, ThresholdConfigForm)
    assert "duplicates" in BiographicDeduplicationConfigForm.rate_help_text
