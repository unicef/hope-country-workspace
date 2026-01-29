import pytest

from country_workspace.workspaces.admin.forms import BaseImportForm
from testutils.factories import CountryProgramFactory, TransformerFactory
from testutils.factories.program import BeneficiaryGroupFactory


@pytest.mark.django_db
def test_base_import_form_includes_transformers_when_program_provided() -> None:
    program = CountryProgramFactory()
    # Create transformers in the same office so they appear in the queryset
    t1 = TransformerFactory(office=program.country_office)
    t2 = TransformerFactory(office=program.country_office)

    form = BaseImportForm(program=program)

    assert "household_transformer" not in form.fields
    assert "individual_transformer" in form.fields

    it_qs = form.fields["individual_transformer"].queryset

    assert list(it_qs.order_by("id")) == [t1, t2]


@pytest.mark.django_db
def test_base_import_form_hides_household_fields_for_people_program(household_checker, individual_checker) -> None:
    beneficiary_group = BeneficiaryGroupFactory(master_detail=False)
    program = CountryProgramFactory(
        beneficiary_group=beneficiary_group,
        household_checker=household_checker,
        individual_checker=individual_checker,
    )
    TransformerFactory(office=program.country_office)

    form = BaseImportForm(program=program)

    assert "household_mapping" not in form.fields
    assert "household_transformer" not in form.fields
    assert "individual_mapping" in form.fields
    assert "individual_transformer" in form.fields


@pytest.mark.django_db
def test_base_import_form_pops_individual_mapping_when_no_individual_checker(household_checker) -> None:
    """When program has no individual_checker, individual_mapping is removed; household fields remain."""
    program = CountryProgramFactory(
        household_checker=household_checker,
        individual_checker=None,
    )
    TransformerFactory(office=program.country_office)

    form = BaseImportForm(program=program)

    assert "household_mapping" not in form.fields
    assert "household_transformer" not in form.fields
    assert "individual_mapping" not in form.fields
    assert "individual_transformer" in form.fields


@pytest.mark.django_db
def test_base_import_form_pops_both_transformers_when_no_program() -> None:
    """When no program is passed, both transformer fields are removed."""
    form = BaseImportForm(program=None)

    assert "household_transformer" not in form.fields
    assert "individual_transformer" not in form.fields
