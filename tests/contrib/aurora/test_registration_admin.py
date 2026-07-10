from types import SimpleNamespace

import pytest
from django.contrib.admin.sites import AdminSite
from pytest_mock import MockerFixture

from country_workspace.contrib.aurora.admin.registration import RegistrationAdmin
from country_workspace.contrib.aurora.forms import RegistrationAdminForm, WriteOnlyTextarea
from country_workspace.contrib.aurora.models import Registration
from tests.contrib.aurora.test_crypto import PRIVATE
from tests.extras.testutils.factories.aurora import ProjectFactory, RegistrationFactory


@pytest.fixture
def registration_admin() -> RegistrationAdmin:
    return RegistrationAdmin(Registration, AdminSite())


@pytest.mark.django_db
def test_write_only_textarea_hides_value() -> None:
    widget = WriteOnlyTextarea()
    assert widget.format_value("secret-key") == ""


def _form_data(registration: Registration, rsa_private_key: str) -> dict:
    return {
        "name": registration.name,
        "active": registration.active,
        "reference_pk": registration.reference_pk,
        "project": registration.project_id,
        "rsa_private_key": rsa_private_key,
    }


@pytest.mark.django_db
def test_registration_admin_form_preserves_key_on_empty_submit() -> None:
    registration = RegistrationFactory(rsa_private_key="stored-key")
    form = RegistrationAdminForm(data=_form_data(registration, ""), instance=registration)

    assert form.is_valid(), form.errors
    assert form.cleaned_data["rsa_private_key"] == "stored-key"


@pytest.mark.django_db
def test_registration_admin_form_empty_key_on_new_instance() -> None:
    project = ProjectFactory()
    registration = Registration(
        name="New registration",
        active=True,
        reference_pk=123,
        project=project,
    )
    form = RegistrationAdminForm(
        data={
            "name": registration.name,
            "active": registration.active,
            "reference_pk": registration.reference_pk,
            "project": project.pk,
            "rsa_private_key": "",
        },
        instance=registration,
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["rsa_private_key"] == ""


@pytest.mark.django_db
def test_registration_admin_form_updates_key_when_provided() -> None:
    registration = RegistrationFactory(rsa_private_key="stored-key")
    private_key = PRIVATE.decode()
    form = RegistrationAdminForm(data=_form_data(registration, private_key), instance=registration)

    assert form.is_valid(), form.errors
    assert form.cleaned_data["rsa_private_key"] == private_key


@pytest.mark.django_db
def test_registration_admin_form_rejects_invalid_private_key() -> None:
    registration = RegistrationFactory(rsa_private_key="stored-key")
    form = RegistrationAdminForm(data=_form_data(registration, "not a private key"), instance=registration)

    assert not form.is_valid()
    assert form.errors["rsa_private_key"] == ["Enter a valid unencrypted RSA private key in PEM format."]


@pytest.mark.django_db
def test_registration_admin_form_rejects_non_rsa_private_key(mocker: MockerFixture) -> None:
    registration = RegistrationFactory(rsa_private_key="stored-key")
    mocker.patch(
        "country_workspace.contrib.aurora.forms.serialization.load_pem_private_key",
        return_value=object(),
    )
    form = RegistrationAdminForm(
        data=_form_data(registration, "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"),
        instance=registration,
    )

    assert not form.is_valid()
    assert form.errors["rsa_private_key"] == ["Enter a valid RSA private key in PEM format."]


def test_has_change_permission_checks_registration_permission(
    mocker: MockerFixture, registration_admin: RegistrationAdmin
) -> None:
    allowed_user = mocker.MagicMock(has_perm=mocker.MagicMock(return_value=True))
    denied_user = mocker.MagicMock(has_perm=mocker.MagicMock(return_value=False))

    assert registration_admin.has_change_permission(SimpleNamespace(user=allowed_user)) is True
    allowed_user.has_perm.assert_called_once_with("aurora.change_registration")

    assert registration_admin.has_change_permission(SimpleNamespace(user=denied_user)) is False
    denied_user.has_perm.assert_called_once_with("aurora.change_registration")


def test_get_readonly_fields_delegates_to_super_when_adding(registration_admin: RegistrationAdmin) -> None:
    request = SimpleNamespace(user=SimpleNamespace(is_superuser=True))
    assert registration_admin.get_readonly_fields(request, None) == ()


@pytest.mark.django_db
def test_get_readonly_fields_leaves_rsa_private_key_editable(registration_admin: RegistrationAdmin) -> None:
    registration = RegistrationFactory()
    request = SimpleNamespace(user=SimpleNamespace(is_superuser=True))
    readonly = registration_admin.get_readonly_fields(request, registration)

    assert "rsa_private_key" not in readonly
    assert "name" in readonly
    assert "reference_pk" in readonly


@pytest.mark.django_db
def test_has_decryption_key_display(registration_admin: RegistrationAdmin) -> None:
    registration = RegistrationFactory(rsa_private_key="pem")
    assert registration_admin.has_decryption_key(registration) is True
    assert registration_admin.has_decryption_key(RegistrationFactory(rsa_private_key="")) is False
