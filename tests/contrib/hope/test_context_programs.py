from unittest.mock import Mock
import pytest
from django.db.models import Model
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.client import HopeClient
from country_workspace.contrib.hope.sync.base import SyncConfig, EndpointConfig, sync_entity
from country_workspace.models import BeneficiaryGroup


def test_sync_programs_missing_beneficiary_group(
    hope_client: HopeClient, mock_model: Mock, mocker: MockerFixture
) -> None:
    hope_client.get.return_value = [{"id": "1", "beneficiary_group": "test_bg"}]
    with pytest.raises(BeneficiaryGroup.DoesNotExist):
        sync_entity(
            SyncConfig(
                model=mock_model,
                endpoint=EndpointConfig(path="fake_path"),
                prepare_defaults=lambda r: {
                    "beneficiary_group": BeneficiaryGroup.objects.get(hope_id=r["beneficiary_group"])
                },
            ),
            hope_client,
        )
    assert not mock_model.objects.update_or_create.called


def test_sync_programs_post_process_save(
    hope_client: HopeClient, delta_sync: bool, mock_model: Mock, mocker: MockerFixture
) -> None:
    mocker.patch("country_workspace.models.BeneficiaryGroup.objects.get", return_value=Mock())
    mocker.patch("country_workspace.models.SyncLog.objects.register_sync")
    default_checkers = {"hh": Mock()}
    mocker.patch(
        "country_workspace.contrib.hope.sync.context_programs.get_default_checkers", return_value=default_checkers
    )
    program = mocker.Mock()
    mock_model.objects.update_or_create.return_value = (program, True)
    hope_client.get.return_value = [{"id": "1", "beneficiary_group": "test_bg"}]

    def post_process(model: Model, _: bool) -> None:
        (setattr(model, "household_checker", default_checkers.get("hh")),)
        (model.save(update_fields=("household_checker", "individual_checker")),)

    sync_entity(
        SyncConfig(
            model=mock_model,
            reference_id="hope_id",
            endpoint=EndpointConfig(path="fake_path"),
            prepare_defaults=lambda r: {
                "beneficiary_group": BeneficiaryGroup.objects.get(hope_id=r["beneficiary_group"])
            },
            post_process=post_process,
            delta_sync=delta_sync,
        ),
        hope_client,
    )
    assert program.save.called
