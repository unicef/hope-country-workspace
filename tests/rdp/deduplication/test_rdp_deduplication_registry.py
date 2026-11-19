import pytest

from country_workspace.models import RdpOperation
from country_workspace.rdp.deduplication.biographic.backend import BIOGRAPHIC_BACKEND
from country_workspace.rdp.deduplication.biometric.backend import BIOMETRIC_BACKEND
from country_workspace.rdp.deduplication.registry import get_deduplication_backend, get_deduplication_backends

pytestmark = pytest.mark.django_db


def test_get_deduplication_backends() -> None:
    assert get_deduplication_backends() == {
        RdpOperation.Type.BIOMETRIC_DEDUPLICATION: BIOMETRIC_BACKEND,
        RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION: BIOGRAPHIC_BACKEND,
    }


@pytest.mark.parametrize(
    ("operation_fixture", "backend"),
    [
        ("biometric_operation", BIOMETRIC_BACKEND),
        ("biographic_operation", BIOGRAPHIC_BACKEND),
        ("ocr_operation", None),
    ],
)
def test_get_deduplication_backend(request: pytest.FixtureRequest, operation_fixture: str, backend: object) -> None:
    assert get_deduplication_backend(request.getfixturevalue(operation_fixture)) is backend
