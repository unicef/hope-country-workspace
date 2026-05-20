import pytest

from country_workspace.models import Individual
from country_workspace.utils.import_flow import build_import_processor
from country_workspace.utils.import_flow.transformations import apply_batch_transformers
from testutils.factories import (
    BatchFactory,
    CountryIndividualFactory,
    CountryProgramFactory,
    MappingImporterFactory,
    TransformerFactory,
)


@pytest.mark.django_db
def test_mapping_runs_before_transformer() -> None:
    program = CountryProgramFactory()
    mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.get_checker_for(Individual),
        rules="gender=sex",
    )
    transformer = TransformerFactory(
        office=program.country_office,
        value_transformations=(
            "function transform(record) { if (record['sex']) { record['sex'] = record['sex'] + '!'; } return record; }"
        ),
    )
    batch = BatchFactory(program=program, country_office=program.country_office)

    processor = build_import_processor(
        program=program,
        model=Individual,
        mapping_id=mapping.id,
        source=batch.source,
    )
    mapped = processor({"gender": "M"})

    assert mapped["sex"] == "M"
    assert "gender" not in mapped

    individual = CountryIndividualFactory(
        batch=batch,
        household=None,
        flex_fields=mapped,
        errors={"old": "error"},
    )

    result = apply_batch_transformers(batch, individual_transformer_id=transformer.id)

    individual.refresh_from_db()
    assert result["transformed_individuals"] == 1
    assert individual.flex_fields["sex"] == "M!"
    assert "gender" not in individual.flex_fields
    assert individual.last_checked is None
    assert individual.errors == {}
