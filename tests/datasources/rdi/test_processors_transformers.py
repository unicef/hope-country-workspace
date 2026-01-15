from unittest.mock import Mock, call

from pytest_mock import MockerFixture

from country_workspace.datasources.rdi import processors


def _base_config() -> dict:
    return {
        "household_id_column": "hh_id",
        "household_label": "hh_label",
        "beneficiary_id_column": "ind_id",
        "first_line": 2,
    }


def test_process_households_uses_transformer_id(mocker: MockerFixture) -> None:
    partial_mock = mocker.patch("country_workspace.datasources.rdi.processors.partial")
    partial_mock.side_effect = [Mock(name="map_partial"), Mock(name="default_partial")]

    job = Mock()
    job.program = Mock()
    batch = Mock()

    config = {
        **_base_config(),
        "household_mapping_id": 1,
        "household_transformer_id": 2,
    }

    processors.process_households([], job, batch, config)

    partial_mock.assert_has_calls(
        [
            call(
                job.program.apply_mapping_importer,
                processors.Household,
                mapping_id=1,
                transformer_id=2,
            ),
            call(job.program.apply_default_fields, processors.Household),
        ]
    )


def test_process_beneficiaries_uses_transformer_id(mocker: MockerFixture) -> None:
    partial_mock = mocker.patch("country_workspace.datasources.rdi.processors.partial")
    partial_mock.side_effect = [Mock(name="map_partial"), Mock(name="default_partial")]

    job = Mock()
    job.program = Mock()
    batch = Mock()

    config = {
        **_base_config(),
        "beneficiary_id_column": "ind_id",
        "people_prefix": "pp_",
        "individual_mapping_id": 5,
        "individual_transformer_id": 6,
    }

    processors.process_beneficiaries([], job, batch, config, household_mapping=None)

    partial_mock.assert_has_calls(
        [
            call(
                job.program.apply_mapping_importer,
                processors.Individual,
                mapping_id=5,
                transformer_id=6,
            ),
            call(job.program.apply_default_fields, processors.Individual),
        ]
    )
