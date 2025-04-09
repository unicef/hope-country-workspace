from io import StringIO

import pytest
from constance.test import override_config
from django import forms

from country_workspace.contrib.hope.sync.context_programs import sync_context_programs, SyncStep


@pytest.fixture(autouse=True)
def setup_definitions(db):
    from testutils.factories import FieldDefinitionFactory

    FieldDefinitionFactory(field_type=forms.ChoiceField)


@pytest.mark.default_cassette("test_sync_all.yaml")
@pytest.mark.vcr
@pytest.mark.xdist_group("remote")
@pytest.mark.parametrize("stdout", [None, StringIO()])
@override_config(HOPE_API_URL="https://dev-hope.unitst.org/api/rest/")
def test_sync_context_programs(stdout):
    assert sync_context_programs(stdout=stdout)
    if stdout:
        assert "fetching" in str(stdout.getvalue())


@pytest.mark.vcr
@pytest.mark.xdist_group("remote")
@override_config(HOPE_API_URL="https://dev-hope.unitst.org/api/rest/")
def test_sync_programs():
    from country_workspace.models import Office

    office = Office.objects.first()
    assert sync_context_programs(step=SyncStep.PROGRAMS, programs_limit_to_office=office)
