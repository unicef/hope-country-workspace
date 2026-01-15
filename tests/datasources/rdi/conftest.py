import pytest
from country_workspace.datasources.rdi.config import Config


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
