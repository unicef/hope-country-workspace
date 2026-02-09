import pytest
from country_workspace.models import Batch
from country_workspace.utils.import_processing import _normalize_source


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(None, None, id="None"),
        pytest.param("", None, id="Empty"),
        pytest.param(Batch.BatchSource.RDI, "XLS", id="RDI"),
        pytest.param("RDI", "XLS", id="RDI String"),
        pytest.param(Batch.BatchSource.KOBO, "KOBO", id="KOBO"),
        pytest.param("KOBO", "KOBO", id="KOBO String"),
        pytest.param(Batch.BatchSource.AURORA, "AURORA", id="AURORA"),
        pytest.param("AURORA", "AURORA", id="AURORA String"),
        pytest.param("CUSTOM", "CUSTOM", id="CUSTOM String"),
    ],
)
def test_normalize_source(source: Batch.BatchSource | str, expected: str | None) -> None:
    assert _normalize_source(source) == expected
