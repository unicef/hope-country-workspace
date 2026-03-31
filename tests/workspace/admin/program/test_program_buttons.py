import pytest
from django.contrib.admin import AdminSite
from django.urls import reverse
from pytest_mock import MockerFixture

from country_workspace.workspaces.admin import program as program_admin_mod
from country_workspace.workspaces.admin.program import CountryProgramAdmin
from country_workspace.workspaces.models import CountryProgram
from country_workspace.models import User
from testutils.perms import user_grant_permissions


pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_site() -> AdminSite:
    return AdminSite()


@pytest.fixture
def country_program_admin_instance(admin_site) -> CountryProgramAdmin:
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
    ("url_name", "permission"),
    [
        ("workspace:workspaces_countryprogram_import_data", "country_workspace.import_program_data"),
        ("workspace:workspaces_countryprogram_import_file_updates", "country_workspace.import_program_data"),
    ],
    ids=["import_data", "import_file_updates"],
)
def test_program_action_permissions(
    user: User,
    client,
    country_program,
    url_name: str,
    permission: str,
) -> None:
    url = reverse(url_name, args=[country_program.pk])

    client.force_login(user)
    client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
    response = client.get(url)
    assert response.status_code == 403

    with user_grant_permissions(user, permission, country_program):
        client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
        response = client.get(url)
        assert response.status_code == 200


@pytest.mark.parametrize(
    ("url_name", "program_fixture"),
    [
        ("workspace:workspaces_countryprogram_household_columns", "country_program_md_true"),
        ("workspace:workspaces_countryprogram_individual_columns", "country_program"),
        ("workspace:workspaces_countryprogram_household_defaults", "country_program_md_true"),
        ("workspace:workspaces_countryprogram_individual_defaults", "country_program"),
        ("workspace:workspaces_countryprogram_household_unique_field", "country_program_md_true"),
        ("workspace:workspaces_countryprogram_individual_unique_field", "country_program"),
    ],
    ids=["hh_columns", "ind_columns", "hh_defaults", "ind_defaults", "hh_unique_field", "ind_unique_field"],
)
def test_columns_and_defaults_permissions(
    user: User,
    client,
    request: pytest.FixtureRequest,
    url_name: str,
    program_fixture: str,
) -> None:
    program = request.getfixturevalue(program_fixture)
    url = reverse(url_name, args=[program.pk])

    client.force_login(user)
    client.post(reverse("workspace:select_tenant"), data={"tenant": program.country_office.pk})
    response = client.get(url)
    assert response.status_code == 403

    with user_grant_permissions(user, "workspaces.change_countryprogram", program):
        client.post(reverse("workspace:select_tenant"), data={"tenant": program.country_office.pk})
        response = client.get(url)
        assert response.status_code == 200


@pytest.mark.parametrize(
    ("group_method", "columns_method", "defaults_method", "unique_method", "ignore_method"),
    [
        (
            "household_group",
            "household_columns",
            "household_defaults",
            "household_unique_field",
            "household_alien_fields_to_ignore",
        ),
        (
            "individual_group",
            "individual_columns",
            "individual_defaults",
            "individual_unique_field",
            "individual_alien_fields_to_ignore",
        ),
    ],
    ids=["household_group", "individual_group"],
)
def test_group_choice_buttons_choices(
    country_program_admin_instance: CountryProgramAdmin,
    mocker: MockerFixture,
    group_method: str,
    columns_method: str,
    defaults_method: str,
    unique_method: str,
    ignore_method: str,
) -> None:
    admin = country_program_admin_instance
    handler = getattr(CountryProgramAdmin, group_method)
    button = mocker.MagicMock()

    handler.func(admin, button)

    assert button.choices == [
        getattr(admin, columns_method),
        getattr(admin, defaults_method),
        getattr(admin, unique_method),
        getattr(admin, ignore_method),
    ]


def test_update_dedup_settings_permissions(
    user: User,
    client,
    country_program,
    mock_dedup_settings_policy,
    mocker: MockerFixture,
) -> None:
    url = reverse("workspace:workspaces_countryprogram_update_dedup_settings", args=[country_program.pk])

    mock_dedup_settings_policy(allowed=True)
    mocker.patch.object(CountryProgramAdmin, "_get_dedup_settings", return_value={})
    client.force_login(user)
    client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
    response = client.get(url)
    assert response.status_code == 403

    with user_grant_permissions(user, "workspaces.change_countryprogram", country_program):
        client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
        response = client.get(url)
        assert response.status_code == 200


def test_update_dedup_settings_post_success(
    user: User,
    client,
    country_program,
    mock_dedup_settings_policy,
    mock_dedup_client,
    mocker: MockerFixture,
    dedup_settings_data,
) -> None:
    url = reverse("workspace:workspaces_countryprogram_update_dedup_settings", args=[country_program.pk])

    mocker.patch.object(
        CountryProgramAdmin,
        "_get_dedup_settings",
        return_value=dedup_settings_data["settings"],
    )
    mock_dedup_settings_policy(allowed=True)

    form = mocker.MagicMock()
    form.is_valid.return_value = True
    form.get_payload.return_value = dedup_settings_data["payload"]
    form_cls = mocker.patch.object(program_admin_mod, "DedupSettingsForm", return_value=form)

    make_client, dedup_client = mock_dedup_client
    mocker.patch.object(
        type(country_program),
        "unicef_id",
        new_callable=mocker.PropertyMock,
        return_value="prg-1",
    )

    client.force_login(user)
    with user_grant_permissions(user, "workspaces.change_countryprogram", country_program):
        client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
        response = client.post(url, data=dedup_settings_data["post_data"])

    assert response.status_code == 302
    assert response.url == reverse("workspace:workspaces_countryprogram_change", args=[country_program.pk])

    args, kwargs = form_cls.call_args
    assert kwargs == {"settings": dedup_settings_data["settings"]}
    assert args[0].dict() == dedup_settings_data["post_data"]

    make_client.assert_called_once_with(group_reference_id="prg-1")
    dedup_client.post_deduplication_set_group_config.assert_called_once_with(payload=dedup_settings_data["payload"])


def test_update_dedup_settings_post_blocked_by_policy(
    user: User,
    client,
    country_program,
    mock_dedup_settings_policy,
    mocker: MockerFixture,
) -> None:
    url = reverse("workspace:workspaces_countryprogram_update_dedup_settings", args=[country_program.pk])

    get_settings = mocker.patch.object(CountryProgramAdmin, "_get_dedup_settings")
    mock_dedup_settings_policy(allowed=False)
    form_cls = mocker.patch.object(program_admin_mod, "DedupSettingsForm")
    make_client = mocker.patch.object(program_admin_mod, "make_dedup_client")

    client.force_login(user)
    with user_grant_permissions(user, "workspaces.change_countryprogram", country_program):
        client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
        response = client.post(url, data={"threshold_1": "0.11"})

    assert response.status_code == 302
    assert response.url == reverse("workspace:workspaces_countryprogram_change", args=[country_program.pk])
    get_settings.assert_not_called()
    form_cls.assert_not_called()
    make_client.assert_not_called()
