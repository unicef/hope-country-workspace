import pytest
from constance.test import override_config
from django.test import override_settings

from country_workspace.utils.constance import GroupChoiceField, ObfuscatedInput, WriteOnlyTextarea, WriteOnlyTextInput


def test_utils_groupchoicefield() -> None:
    field = GroupChoiceField()
    assert field


# LdapDNField


# ObfuscatedInput
def test_obfuscatedinput() -> None:
    field = ObfuscatedInput()
    assert field.render("name", "value") == '<input type="hidden" name="name" value="value">Set'


# WriteOnlyTextarea
def test_writeonlytextarea() -> None:
    field = WriteOnlyTextarea()
    assert field.render("name", "value") == (
        '<textarea name="name" cols="40" rows="10" '
        'placeholder="***" autocomplete="new-password" spellcheck="false">\n</textarea>'
    )


@override_settings(
    CONSTANCE_DEFAULTS_MASK="***",
    CONSTANCE_CONFIG={"HOPE_API_TOKEN": ("very-secret-token", "desc")},
    CONFIG={"HOPE_API_TOKEN": ("very-secret-token", "desc")},
)
@pytest.mark.parametrize(
    ("posted", "expected"),
    [
        ("", "abc"),
        ("***", "very-secret-token"),
        ("new-value", "new-value"),
    ],
    ids=["empty_keeps_current", "mask_resets_default", "passthrough_value"],
)
def test_writeonlyinput_value_from_datadict(posted: str, expected: str) -> None:
    field = WriteOnlyTextInput()

    with override_config(HOPE_API_TOKEN="abc"):
        assert field.value_from_datadict({"HOPE_API_TOKEN": posted}, {}, "HOPE_API_TOKEN") == expected
