from unittest.mock import Mock
import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.sync.base import BaseSync, SyncConfig, EndpointConfig
from country_workspace.models import BeneficiaryGroup


def test_sync_programs_missing_beneficiary_group(base_sync: BaseSync, mock_model: Mock, mocker: MockerFixture) -> None:
    base_sync.client.get.return_value = [{"id": "1", "beneficiary_group": "test_bg"}]
    with pytest.raises(BeneficiaryGroup.DoesNotExist):
        base_sync.sync_entity(
            SyncConfig(
                model=mock_model,
                endpoint=EndpointConfig(path="fake_path"),
                prepare_defaults=lambda r: {
                    "beneficiary_group": BeneficiaryGroup.objects.get(hope_id=r["beneficiary_group"])
                },
            )
        )
    assert not mock_model.objects.update_or_create.called


def test_sync_programs_post_process_save(base_sync: BaseSync, mock_model: Mock, mocker: MockerFixture) -> None:
    mocker.patch("country_workspace.models.BeneficiaryGroup.objects.get", return_value=Mock())
    mocker.patch("country_workspace.models.SyncLog.objects.register_sync")
    program = mocker.Mock()
    mock_model.objects.update_or_create.return_value = (program, True)
    base_sync.default_checkers = {"hh": Mock()}
    base_sync.client.get.return_value = [{"id": "1", "beneficiary_group": "test_bg"}]
    base_sync.sync_entity(
        SyncConfig(
            model=mock_model,
            reference_id="hope_id",
            endpoint=EndpointConfig(path="fake_path"),
            prepare_defaults=lambda r: {
                "beneficiary_group": BeneficiaryGroup.objects.get(hope_id=r["beneficiary_group"])
            },
            post_process=lambda p, c: (
                setattr(p, "household_checker", base_sync.default_checkers.get("hh")),
                p.save(update_fields=("household_checker", "individual_checker")),
            ),
        )
    )
    assert program.save.called
