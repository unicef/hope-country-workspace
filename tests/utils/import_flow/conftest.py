import pytest
from pytest_mock import MockerFixture


@pytest.fixture
def import_flow_batch(mocker: MockerFixture):
    batch = mocker.MagicMock()
    batch.program.is_master_detail = True

    batch.households_qs = mocker.MagicMock(name="households_qs")
    batch.individuals_qs = mocker.MagicMock(name="individuals_qs")

    batch.household_set.filter.return_value = batch.households_qs
    batch.individual_set.filter.return_value = batch.individuals_qs

    return batch
