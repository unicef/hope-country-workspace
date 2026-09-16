from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from openpyxl import Workbook
from openpyxl.drawing.image import Image as RDIImage

from country_workspace.datasources.rdi.config import Config
from country_workspace.utils.flex_files import FlexFileContent


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def config(request) -> Config:
    return {
        "batch_name": "batch_name",
        "validate_mode": "none",
        "master_detail": request.param,
        "beneficiary_id_column": "beneficiary_id",
        "send_to": "send_to",
        "household_id_column": "household_id",
        "household_label": "household_label",
        "people_prefix": "pp_",
        "first_line": 2,
        "household_mapping_id": None,
        "individual_mapping_id": None,
        "household_transformer_id": None,
        "individual_transformer_id": None,
    }


@pytest.fixture
def png_bytes() -> bytes:
    """A real one-pixel PNG, so that images survive an actual xlsx round trip."""
    buffer = BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def photo_content(png_bytes: bytes) -> FlexFileContent:
    return FlexFileContent(content=png_bytes, mimetype="image/png", filename="photo.png")


@pytest.fixture
def workbook_with_image(tmp_path: Path, png_bytes: bytes) -> str:
    """An xlsx whose only image is anchored in the first cell of the first data row."""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "first"
    worksheet["A1"] = "photo"
    worksheet.add_image(RDIImage(BytesIO(png_bytes)), "A2")
    path = tmp_path / "with_image.xlsx"
    workbook.save(path)
    return str(path)
