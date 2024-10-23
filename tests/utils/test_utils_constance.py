from constance.test import override_config

from country_workspace.utils.constance import GroupChoiceField, ObfuscatedInput, WriteOnlyInput, WriteOnlyTextarea


def test_utils_groupchoicefield():
    field = GroupChoiceField()
    assert field


# LdapDNField


# ObfuscatedInput
def test_obfuscatedinput():
    field = ObfuscatedInput()
    assert field.render("name", "value") == '<input type="hidden" name="name" value="value">Set'


# WriteOnlyTextarea
def test_writeonlytextarea():
    field = WriteOnlyTextarea()
    assert field.render("name", "value") == '<textarea name="name" cols="40" rows="10">\n***</textarea>'


@override_config(HOPE_API_TOKEN="abc")
def test_writeonlyinput():
    field = WriteOnlyInput()
    assert field.render("name", "value")
    assert field.value_from_datadict({"HOPE_API_TOKEN": "***"}, {}, "HOPE_API_TOKEN") == "abc"
    assert field.value_from_datadict({"HOPE_API_TOKEN": "123"}, {}, "HOPE_API_TOKEN") == "123"
