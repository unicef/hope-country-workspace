import pytest
from django.test import RequestFactory
from django.urls import reverse

from country_workspace.workspaces.sites import workspace


@pytest.fixture
def rf() -> RequestFactory:
    return RequestFactory()


@pytest.mark.parametrize(
    ("url_name", "expected_admin"),
    [
        ("workspace:workspaces_countryprogram_changelist", "CountryProgramAdmin"),
        ("workspace:workspaces_countryhousehold_changelist", "CountryHouseholdAdmin"),
        ("workspace:workspaces_countryindividual_changelist", "CountryIndividualAdmin"),
        ("workspace:workspaces_countrybatch_changelist", "CountryBatchAdmin"),
        ("workspace:workspaces_countrymappingimporter_changelist", "CountryMappingImporterAdmin"),
        ("workspace:workspaces_countryrdp_changelist", "CountryRdpAdmin"),
        ("workspace:workspaces_countryasyncjob_changelist", "CountryJobAdmin"),
    ],
    ids=[
        "program",
        "household",
        "individual",
        "batch",
        "mapping_importer",
        "rdp",
        "async_job",
    ],
)
def test_current_modeladmin_for_known_changelist(rf, url_name, expected_admin):
    request = rf.get(reverse(url_name))
    assert workspace._current_modeladmin(request) == expected_admin


def test_current_modeladmin_matches_prefix_subpaths(rf):
    """URL names that *start with* a known prefix (e.g. ``..._import_data``) also map.

    Exercises the ``url_name.startswith(prefix + "_")`` branch via the
    Households change-list ``Import Data`` button, whose URL name is
    ``workspaces_countryhousehold_import_data``.
    """
    request = rf.get(reverse("workspace:workspaces_countryhousehold_import_data"))
    assert workspace._current_modeladmin(request) == "CountryHouseholdAdmin"


def test_current_modeladmin_returns_none_when_path_does_not_resolve(rf):
    """``Resolver404`` is swallowed and the function returns ``None``."""
    request = rf.get("/this/path/definitely/does/not/exist/")
    assert workspace._current_modeladmin(request) is None


def test_current_modeladmin_returns_none_for_unmapped_resolved_url(rf):
    """A URL that resolves but isn't in the lookup table returns ``None``."""
    request = rf.get(reverse("workspace:index"))
    assert workspace._current_modeladmin(request) is None
