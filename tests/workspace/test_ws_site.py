from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from testutils.perms import user_grant_permissions
from testutils.utils import select_office

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.models import User
    from country_workspace.workspaces.models import CountryBatch


@pytest.fixture
def batch():
    from testutils.factories import CountryBatchFactory

    return CountryBatchFactory()


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables") -> "CWTestApp":
    return django_app_factory(csrf_checks=False)


def test_autocomplete_view(app, user: "User", batch: "CountryBatch"):
    url = reverse("workspace:autocomplete")
    res = app.get(url)
    assert res.location == "/login/"

    app.set_user(user)
    with user_grant_permissions(user, "workspaces.view_countrybatch", batch.program):
        with select_office(app, batch.country_office, batch.program):
            res = app.get(f"{url}?app_label=country_workspace&model_name=individual&field_name=batch&term={batch.name}")
            assert res.json == {"pagination": {"more": False}, "results": [{"id": str(batch.id), "text": batch.name}]}

        with select_office(app, batch.country_office, batch.program):
            res = app.get(f"{url}?&term={batch.name}", expect_errors=True)
            assert res.status_code == 403
            res = app.get(
                f"{url}?app_label=country_workspace&model_name=xxx&field_name=batch&term={batch.name}",
                expect_errors=True,
            )
            assert res.status_code == 403
            res = app.get(
                f"{url}?app_label=country_workspace&model_name=individual&field_name=xxx&term={batch.name}",
                expect_errors=True,
            )
            assert res.status_code == 403
            res = app.get(
                f"{url}?app_label=country_workspace&model_name=individual&field_name=name&term={batch.name}",
                expect_errors=True,
            )
            assert res.status_code == 403
            res = app.get(
                f"{url}?app_label=country_workspace&model_name=individual&field_name=country_office&term={batch.name}",
                expect_errors=True,
            )
            assert res.status_code == 403


def test_program_cleanup_blocks_workspace(app, user: "User", batch: "CountryBatch") -> None:
    url = reverse("workspace:workspaces_countrybatch_changelist")
    app.set_user(user)

    with user_grant_permissions(user, "workspaces.view_countrybatch", batch.program):
        with select_office(app, batch.country_office, batch.program):
            batch.program.cleanup_in_progress = True
            batch.program.save(update_fields=["cleanup_in_progress"])

            res = app.get(url)

    assert res.location == reverse("workspace:workspaces_countryprogram_change", args=[batch.program_id])
