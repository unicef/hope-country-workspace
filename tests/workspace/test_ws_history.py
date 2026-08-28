from typing import TYPE_CHECKING

import pghistory
import pytest
from django.urls import reverse
from pyquery import PyQuery
from testutils.utils import select_office

from country_workspace.utils.flex_fields import (
    Base64ImageField,
    describe_flex_file_value,
    to_storage_flex_file_value,
)

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.models import User
    from country_workspace.workspaces.models import CountryIndividual


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


@pytest.fixture
def program():
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory()


@pytest.fixture
def individual():
    from testutils.factories import CountryIndividualFactory

    individual = CountryIndividualFactory(household__batch__program__individual_checker__fields=["first_name"])
    with pghistory.context(user={"email": "<EMAIL>", "username": "user #1"}):
        individual.flex_fields = {"first_name": "Name 1"}
        individual.save()
        individual.flex_fields = {"first_name": "Name 2"}
        individual.save()

    return individual


def test_individual_history(app, individual: "CountryIndividual"):
    url = reverse("workspace:workspaces_countryindividual_history", args=[individual.pk])
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        etag = res.headers["Etag"]

        assert res.status_code == 200
        pq = PyQuery(res.content)
        old_values = [node.text.strip() for node in pq("table.history tbody tr td div.old_value")]
        new_values = [node.text.strip() for node in pq("table.history tbody tr td div.new_value")]
        transitions = set(zip(old_values, new_values, strict=False))
        assert ("Name 1", "Name 2") in transitions
        assert ("", "Name 1") in transitions

        res = app.get(url, headers={"etag": etag})
        assert res.status_code == 304


def test_individual_history_tracks_file_changes(app):
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
        DataCheckerFactory,
    )

    checker = DataCheckerFactory(fields=[("photo", Base64ImageField)])
    program = CountryProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(batch=batch, household=household, flex_fields={})

    with pghistory.context(user={"email": "<EMAIL>", "username": "user #1"}):
        individual.apply_flex_payload({"photo": "data:image/png;base64,AAAA"})
        individual.save(update_fields=["flex_fields", "flex_files"])
        individual.apply_flex_payload({"photo": "data:image/png;base64,BBBB"})
        individual.save(update_fields=["flex_fields", "flex_files"])

    url = reverse("workspace:workspaces_countryindividual_history", args=[individual.pk])
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        assert b"base64,AAAA" not in res.content
        assert b"base64,BBBB" not in res.content
        pq = PyQuery(res.content)
        old_values = [node.text.strip() for node in pq("table.history tbody tr td div.old_value")]
        new_values = [node.text.strip() for node in pq("table.history tbody tr td div.new_value")]
        transitions = set(zip(old_values, new_values, strict=False))
        assert (
            describe_flex_file_value(to_storage_flex_file_value("data:image/png;base64,AAAA")),
            describe_flex_file_value(to_storage_flex_file_value("data:image/png;base64,BBBB")),
        ) in transitions
