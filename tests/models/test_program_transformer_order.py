import pytest

from country_workspace.models import Individual
from testutils.factories import CountryProgramFactory, MappingImporterFactory, TransformerFactory


@pytest.mark.django_db
def test_mapping_runs_before_transformer():
    program = CountryProgramFactory()
    mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.get_checker_for(Individual),
        rules="gender=sex",
    )
    transformer = TransformerFactory(
        office=program.country_office,
        value_transformations="function t(d){ if(d['sex']){ d['sex'] = d['sex'] + '!'; } return d; }",
    )

    data = {"gender": "M"}
    result = program.apply_mapping_importer(Individual, data, mapping_id=mapping.id, transformer_id=transformer.id)

    assert result.get("sex") == "M!"
    assert "gender" not in result
