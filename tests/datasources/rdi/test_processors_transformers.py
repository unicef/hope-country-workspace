from pytest_mock import MockerFixture

from country_workspace.datasources.rdi import processors


def _base_config() -> dict:
    return {
        "batch_name": "batch",
        "master_detail": False,
        "household_id_column": "hh_id",
        "household_label": "hh_label",
        "beneficiary_id_column": "ind_id",
        "people_prefix": "pp_",
        "first_line": 2,
        "household_mapping_id": 1,
        "individual_mapping_id": 5,
        "household_transformer_id": 2,
        "individual_transformer_id": 6,
    }


def test_process_households_uses_mapping_id(mocker: MockerFixture) -> None:
    build_processor = mocker.patch("country_workspace.datasources.rdi.processors.build_import_processor")
    build_processor.return_value = mocker.MagicMock(name="processor")

    job = mocker.MagicMock()
    batch = mocker.MagicMock()
    config = _base_config()

    processors.process_households([], job, batch, config)

    build_processor.assert_called_once_with(
        program=job.program,
        model=processors.Household,
        mapping_id=1,
        source=processors.Batch.BatchSource.RDI,
    )


def test_process_beneficiaries_uses_mapping_id(mocker: MockerFixture) -> None:
    build_processor = mocker.patch("country_workspace.datasources.rdi.processors.build_import_processor")
    build_processor.return_value = mocker.MagicMock(name="processor")

    job = mocker.MagicMock()
    batch = mocker.MagicMock()
    config = _base_config()

    processors.process_beneficiaries([], job, batch, config, household_mapping=None)

    build_processor.assert_called_once_with(
        program=job.program,
        model=processors.Individual,
        mapping_id=5,
        source=processors.Batch.BatchSource.RDI,
    )


def test_import_from_rdi_passes_transformers_to_postprocessing(mocker: MockerFixture) -> None:
    config = _base_config()

    job = mocker.MagicMock()
    job.config = config

    mocker.patch("country_workspace.datasources.rdi.processors.atomic")
    mocker.patch("country_workspace.datasources.rdi.processors.batch_ctx")
    batch_cls = mocker.patch("country_workspace.datasources.rdi.processors.Batch")
    batch = batch_cls.objects.create.return_value

    mocker.patch("country_workspace.datasources.rdi.processors.read_sheets", return_value=([],))
    mocker.patch("country_workspace.datasources.rdi.processors.process_beneficiaries", return_value={})
    postprocessing = mocker.patch("country_workspace.datasources.rdi.processors.run_batch_postprocessing")
    mocker.patch("country_workspace.datasources.rdi.processors.detect_and_mark_collisions_for_batch")

    processors.import_from_rdi(job)

    postprocessing.assert_called_once_with(
        batch,
        household_transformer_id=2,
        individual_transformer_id=6,
    )
