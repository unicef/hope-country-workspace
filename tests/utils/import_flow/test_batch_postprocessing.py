from pytest_mock import MockerFixture

from country_workspace.utils.import_flow.batch_postprocessing import run_batch_postprocessing


MOD = "country_workspace.utils.import_flow.batch_postprocessing"


def test_run_batch_postprocessing_runs_all_steps_for_master_detail(mocker: MockerFixture, import_flow_batch) -> None:
    batch = import_flow_batch
    sync_household_refs = mocker.MagicMock()
    sync_collector_links = mocker.patch(f"{MOD}.sync_collector_links", return_value=2)
    apply_batch_transformers = mocker.patch(
        f"{MOD}.apply_batch_transformers",
        return_value={"households_transformed": 3, "individuals_transformed": 4},
    )

    result = run_batch_postprocessing(
        batch,
        household_transformer_id=10,
        individual_transformer_id=20,
        sync_household_refs=sync_household_refs,
    )

    assert result == {
        "collector_links": 2,
        "households_transformed": 3,
        "individuals_transformed": 4,
    }
    sync_household_refs.assert_called_once_with(batch)
    batch.individual_set.filter.assert_called_once_with(removed=False)
    sync_collector_links.assert_called_once_with(batch.individuals_qs)
    apply_batch_transformers.assert_called_once_with(
        batch,
        household_transformer_id=10,
        individual_transformer_id=20,
    )


def test_run_batch_postprocessing_skips_household_refs_without_syncer(mocker: MockerFixture, import_flow_batch) -> None:
    batch = import_flow_batch
    sync_collector_links = mocker.patch(f"{MOD}.sync_collector_links", return_value=0)
    apply_batch_transformers = mocker.patch(f"{MOD}.apply_batch_transformers", return_value={})

    result = run_batch_postprocessing(batch)

    assert result == {"collector_links": 0}
    sync_collector_links.assert_called_once_with(batch.individuals_qs)
    apply_batch_transformers.assert_called_once_with(
        batch,
        household_transformer_id=None,
        individual_transformer_id=None,
    )


def test_run_batch_postprocessing_skips_household_refs_for_people_only(
    mocker: MockerFixture, import_flow_batch
) -> None:
    batch = import_flow_batch
    batch.program.is_master_detail = False
    sync_household_refs = mocker.MagicMock()
    mocker.patch(f"{MOD}.sync_collector_links", return_value=0)
    mocker.patch(f"{MOD}.apply_batch_transformers", return_value={})

    run_batch_postprocessing(batch, sync_household_refs=sync_household_refs)

    sync_household_refs.assert_not_called()


def test_run_batch_postprocessing_runs_household_refs_before_links_and_transformers(
    mocker: MockerFixture,
    import_flow_batch,
) -> None:
    batch = import_flow_batch
    calls: list[str] = []

    def sync_household_refs(_batch) -> None:
        calls.append("household_refs")

    def sync_collector_links(_qs) -> int:
        calls.append("collector_links")
        return 1

    def apply_batch_transformers(*_args, **_kwargs) -> dict[str, int]:
        calls.append("transformers")
        return {"households_transformed": 1}

    mocker.patch(f"{MOD}.sync_collector_links", side_effect=sync_collector_links)
    mocker.patch(f"{MOD}.apply_batch_transformers", side_effect=apply_batch_transformers)

    result = run_batch_postprocessing(batch, sync_household_refs=sync_household_refs)

    assert calls == ["household_refs", "collector_links", "transformers"]
    assert result == {"collector_links": 1, "households_transformed": 1}
