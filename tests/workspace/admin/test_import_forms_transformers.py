import pytest

from country_workspace.workspaces.admin.forms import BaseImportForm
from testutils.factories import CountryProgramFactory, TransformerFactory


@pytest.mark.django_db
def test_base_import_form_includes_transformers_when_program_provided() -> None:
    program = CountryProgramFactory()
    # Create transformers in the same office so they appear in the queryset
    t1 = TransformerFactory(office=program.country_office)
    t2 = TransformerFactory(office=program.country_office)

    form = BaseImportForm(program=program)

    assert "household_transformer" in form.fields
    assert "individual_transformer" in form.fields

    ht_qs = form.fields["household_transformer"].queryset
    it_qs = form.fields["individual_transformer"].queryset

    assert list(ht_qs.order_by("id")) == [t1, t2]
    assert list(it_qs.order_by("id")) == [t1, t2]
