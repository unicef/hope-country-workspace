import json
from pathlib import Path
from random import sample

import vcr
from vcr.record_mode import RecordMode

from country_workspace.sync.office import (
    sync_maritalstatus,
    sync_observeddisability,
    sync_offices,
    sync_programs,
    sync_relationship,
    sync_residencestatus, sync_all,
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
        except Exception as e:
            raise
    return response


my_vcr = vcr.VCR(
    before_record_response=scrub_string,
    filter_headers=["authorization"],
    record_mode=RecordMode.ONCE,
)


def test_sync_all():
    with my_vcr.use_cassette(Path(__file__).parent / "sync_all.yaml"):
        assert sync_all()


def test_sync_programs():
    with my_vcr.use_cassette(Path(__file__).parent / "sync_programs.yaml"):
        assert sync_offices()
        assert sync_programs()


def test_sync_maritalstatus():
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
