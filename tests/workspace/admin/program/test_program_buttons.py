import pytest
from django.contrib.admin import AdminSite
from django.urls import reverse
from pytest_mock import MockerFixture

from country_workspace.models import User
from country_workspace.workspaces.admin.program import CountryProgramAdmin
from country_workspace.workspaces.models import CountryProgram
from testutils.perms import user_grant_permissions

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_site() -> AdminSite:
    return AdminSite()


@pytest.fixture
def country_program_admin_instance(admin_site: AdminSite) -> CountryProgramAdmin:
    return CountryProgramAdmin(CountryProgram, admin_site)


@pytest.fixture
def country_program(country_office):
    from testutils.factories import CountryProgramFactory

    program = CountryProgramFactory(country_office=country_office)
    program.biometric_deduplication_enabled = True
    program.save(update_fields=["biometric_deduplication_enabled"])
    return program


@pytest.fixture
def country_program_md_true(country_program):
    country_program.beneficiary_group.master_detail = True
    country_program.beneficiary_group.save(update_fields=["master_detail"])
    return country_program


@pytest.mark.parametrize(
    "case",
    [
        ("workspace:workspaces_countryprogram_import_data", "country_workspace.import_program_data"),
        ("workspace:workspaces_countryprogram_import_file_updates", "country_workspace.import_program_data"),
    ],
    ids=["import_data", "import_file_updates"],
)
def test_program_action_permissions(user: User, client, country_program, case) -> None:
    url_name, permission = case
    url = reverse(url_name, args=[country_program.pk])

    client.force_login(user)
    client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
    assert client.get(url).status_code == 403

    with user_grant_permissions(user, permission, country_program):
        client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
        assert client.get(url).status_code == 200


@pytest.mark.parametrize(
    "case",
    [
        ("workspace:workspaces_countryprogram_household_columns", "country_program_md_true"),
        ("workspace:workspaces_countryprogram_individual_columns", "country_program"),
        ("workspace:workspaces_countryprogram_household_defaults", "country_program_md_true"),
        ("workspace:workspaces_countryprogram_individual_defaults", "country_program"),
    ],
    ids=["hh_columns", "ind_columns", "hh_defaults", "ind_defaults"],
)
def test_columns_and_defaults_permissions(user: User, client, request: pytest.FixtureRequest, case) -> None:
    url_name, fixture_name = case
    program = request.getfixturevalue(fixture_name)
    url = reverse(url_name, args=[program.pk])

    client.force_login(user)
    client.post(reverse("workspace:select_tenant"), data={"tenant": program.country_office.pk})
    assert client.get(url).status_code == 403

    with user_grant_permissions(user, "workspaces.change_countryprogram", program):
        client.post(reverse("workspace:select_tenant"), data={"tenant": program.country_office.pk})
        assert client.get(url).status_code == 200


@pytest.mark.parametrize(
    "case",
    [
        ("household_group", "household_columns", "household_defaults", "household_alien_fields_to_ignore"),
        ("individual_group", "individual_columns", "individual_defaults", "individual_alien_fields_to_ignore"),
    ],
    ids=["household", "individual"],
)
def test_group_choice_buttons(country_program_admin_instance: CountryProgramAdmin, mocker: MockerFixture, case) -> None:
    group_method, columns_method, defaults_method, ignore_method = case
    button = mocker.MagicMock()

    getattr(CountryProgramAdmin, group_method).func(country_program_admin_instance, button)

    assert button.choices == [
        getattr(country_program_admin_instance, columns_method),
        getattr(country_program_admin_instance, defaults_method),
        getattr(country_program_admin_instance, ignore_method),
    ]


def test_update_dedup_settings_permissions(
    user: User,
    client,
    country_program,
    mock_dedup_settings_policy,
    mocker: MockerFixture,
) -> None:
    url = reverse("workspace:workspaces_countryprogram_update_dedup_settings", args=[country_program.pk])

    mock_dedup_settings_policy()
    mocker.patch.object(CountryProgramAdmin, "_get_dedup_settings", return_value={})
    client.force_login(user)

    client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
    assert client.get(url).status_code == 403

    with user_grant_permissions(user, "workspaces.change_countryprogram", country_program):
        client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
        assert client.get(url).status_code == 200
