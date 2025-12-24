import pytest
from django.contrib.admin import AdminSite
from django.urls import reverse
from unittest.mock import MagicMock

from country_workspace.workspaces.admin import CountryProgramAdmin
from country_workspace.workspaces.models import CountryProgram
from country_workspace.models import User
from testutils.factories import CountryProgramFactory, OfficeFactory
from testutils.perms import user_grant_permissions


@pytest.fixture
def admin_site():
    return AdminSite()


@pytest.fixture
def country_program_admin_instance(admin_site) -> CountryProgramAdmin:
    return CountryProgramAdmin(CountryProgram, admin_site)


@pytest.fixture
def country_office():
    return OfficeFactory()


@pytest.fixture
def country_program(country_office):
    return CountryProgramFactory(country_office=country_office)


@pytest.fixture
def country_program_md_true(country_program):
    country_program.beneficiary_group.master_detail = True
    country_program.save()
    return country_program


@pytest.mark.django_db  # ERA001
def test_import_data_permissions(user, country_program_admin_instance, country_program, client):
    url = reverse("workspace:workspaces_countryprogram_import_data", args=[country_program.pk])
    client.force_login(user)
    client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
    response = client.get(url)
    assert response.status_code == 403

    with user_grant_permissions(user, "country_workspace.import_program_data", country_program):
        client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
        response = client.get(url)
        assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("url_name", "program_fixture"),
    [
        ("workspace:workspaces_countryprogram_household_columns", "country_program_md_true"),
        ("workspace:workspaces_countryprogram_individual_columns", "country_program"),
        ("workspace:workspaces_countryprogram_household_defaults", "country_program_md_true"),
        ("workspace:workspaces_countryprogram_individual_defaults", "country_program"),
    ],
    ids=["hh_columns", "ind_columns", "hh_defaults", "ind_defaults"],
)
def test_columns_and_defaults_permissions(
    user: User,
    country_program_admin_instance: CountryProgramAdmin,
    client: MagicMock,
    request: pytest.FixtureRequest,
    url_name: str,
    program_fixture: str,
):
    program = request.getfixturevalue(program_fixture)
    url = reverse(url_name, args=[program.pk])

    client.post(reverse("workspace:select_tenant"), data={"tenant": program.country_office.pk})
    client.force_login(user)
    response = client.get(url)
    assert response.status_code == 403

    with user_grant_permissions(user, "workspaces.change_countryprogram", program):
        client.post(reverse("workspace:select_tenant"), data={"tenant": program.country_office.pk})
        response = client.get(url)
        assert response.status_code == 200


@pytest.mark.django_db
def test_import_file_updates_permissions(user, country_program_admin_instance, country_program, client):
    url = reverse("workspace:workspaces_countryprogram_import_file_updates", args=[country_program.pk])
    client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
    client.force_login(user)
    response = client.get(url)
    assert response.status_code == 403

    with user_grant_permissions(user, "country_workspace.import_program_data", country_program):
        client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
        response = client.get(url)
        assert response.status_code == 200


@pytest.mark.parametrize(
    ("group_method", "columns_method", "defaults_method", "ignore_method"),
    [
        ("household_group", "household_columns", "household_defaults", "household_alien_fields_to_ignore"),
        ("individual_group", "individual_columns", "individual_defaults", "individual_alien_fields_to_ignore"),
    ],
    ids=["household_group", "individual_group"],
)
def test_group_choice_buttons_choices(
    country_program_admin_instance: CountryProgramAdmin,
        group_method: str,
        columns_method: str,
        defaults_method: str,
        ignore_method: str,
) -> None:
    admin = country_program_admin_instance
    handler = getattr(CountryProgramAdmin, group_method)

    button = MagicMock()

    # Call the original function behind @choice
    handler.func(admin, button)

    assert button.choices == [
        getattr(admin, columns_method),
        getattr(admin, defaults_method),
        getattr(admin, ignore_method),
    ]
