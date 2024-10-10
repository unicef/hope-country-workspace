import json
from pathlib import Path
from random import sample

from django import forms

import pytest
import vcr
from vcr.record_mode import RecordMode

from country_workspace.sync.office import (
    sync_all,
    sync_maritalstatus,
    sync_observeddisability,
    sync_offices,
    sync_programs,
    sync_relationship,
    sync_residencestatus,
)


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
    from django.contrib.contenttypes.models import ContentType

    from testutils.factories import FieldDefinitionFactory

    from country_workspace.models import MaritalStatus, ResidenceStatus

    for m in [MaritalStatus, ResidenceStatus]:
        FieldDefinitionFactory(
            field_type=forms.ChoiceField,
            content_type=ContentType.objects.get_for_model(m),
        )


def test_sync_all():
    with my_vcr.use_cassette(Path(__file__).parent / "sync_all.yaml"):
        assert sync_all()


def test_sync_programs():
    with my_vcr.use_cassette(Path(__file__).parent / "sync_programs.yaml"):
        assert sync_offices()
        assert sync_programs()


def test_sync_maritalstatus(db):
    with my_vcr.use_cassette(Path(__file__).parent / "sync_maritalstatus.yaml"):
        assert sync_maritalstatus()


def test_sync_relationship():
    with my_vcr.use_cassette(Path(__file__).parent / "sync_relationship.yaml"):
        assert sync_relationship()


def test_sync_observeddisability():
    with my_vcr.use_cassette(Path(__file__).parent / "sync_observeddisability.yaml"):
        assert sync_observeddisability()


def test_sync_residencestatus():
    with my_vcr.use_cassette(Path(__file__).parent / "sync_residencestatus.yaml"):
        assert sync_residencestatus()
