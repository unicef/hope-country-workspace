import pytest
from unittest.mock import MagicMock

from country_workspace.workspaces.admin.forms import ImportFileForm


@pytest.fixture(params=[True, False, None], ids=["master_detail", "people_only", "no_beneficiary_group"])
def beneficiary_group(request):
    if request.param is None:
        return None
    return MagicMock(master_detail=request.param)


def test_import_file_form_init(beneficiary_group):
    form = ImportFileForm(beneficiary_group=beneficiary_group)
    beneficiary_field = form.fields["beneficiary_id_column"]

    if beneficiary_group is None:
        assert "household_id_column" in form.fields
        assert "household_label" in form.fields
        assert "people_prefix" in form.fields
        assert "beneficiary_id_column" in form.fields

    elif beneficiary_group.master_detail:
        assert "household_id_column" in form.fields
        assert "household_label" in form.fields

        assert "people_prefix" not in form.fields

        assert "individual record" in beneficiary_field.help_text
        assert beneficiary_field.label == "Individual id column"
        assert beneficiary_field.initial == "individual_id"

    else:
        assert "household_id_column" not in form.fields
        assert "household_label" not in form.fields

        assert "people_prefix" in form.fields

        assert "people record" in beneficiary_field.help_text
        assert beneficiary_field.label == "People id column"
        assert beneficiary_field.initial == "pp_index_id"
