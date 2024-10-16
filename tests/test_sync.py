import json
from pathlib import Path
from random import sample

from django import forms

import pytest
import vcr
from vcr.record_mode import RecordMode

from country_workspace.sync.office import sync_all, sync_lookups, sync_offices, sync_programs


def scrub_string(response):
    if response["status"]["code"] == 200:
        try:
            if payload := response["body"]["string"]:
                data = json.loads(payload.decode())
                if "results" in data:
                    for r in data["results"]:
                        s = r["name"]
                        r["name"] = "".join(sample(s, len(s)))
                    response["body"]["string"] = json.dumps(data).encode()
        except Exception:
            pass
    return response


my_vcr = vcr.VCR(
    before_record_response=scrub_string,
    filter_headers=["authorization"],
    record_mode=RecordMode.ONCE,
)


@pytest.fixture(autouse=True)
def setup_definitions(db):
    from testutils.factories import FieldDefinitionFactory

    FieldDefinitionFactory(field_type=forms.ChoiceField)


def test_sync_all():
    with my_vcr.use_cassette(Path(__file__).parent / "sync_all.yaml"):
        assert sync_all()


def test_sync_programs():
    with my_vcr.use_cassette(Path(__file__).parent / "sync_programs.yaml"):
        assert sync_offices()
        assert sync_programs()


def test_sync_lookup(force_migrated_records):
    with my_vcr.use_cassette(Path(__file__).parent / "sync_lookups.yaml"):
        assert sync_lookups()
