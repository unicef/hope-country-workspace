from io import StringIO

import pytest
from django import forms

from country_workspace.contrib.hope.sync.office import sync_all, sync_beneficiary_groups, sync_offices, sync_programs


@pytest.fixture(autouse=True)
def setup_definitions(db):
    from testutils.factories import FieldDefinitionFactory

    FieldDefinitionFactory(field_type=forms.ChoiceField)


@pytest.mark.default_cassette("test_sync_all.yaml")
@pytest.mark.vcr
@pytest.mark.xdist_group("remote")
@pytest.mark.parametrize("stdout", [None, StringIO()])
def test_sync_all(stdout):
    assert sync_all(stdout)
    if stdout:
        assert "Fetching" in str(stdout.getvalue())


@pytest.mark.vcr
@pytest.mark.xdist_group("remote")
def test_sync_programs():
    from country_workspace.models import Office

    assert sync_offices()
    assert sync_programs()
    assert sync_beneficiary_groups()

    office = Office.objects.first()

    assert sync_programs(office)
