import re

from django import forms

# Keep in sync with HOPE's `hope.models.individual.LATIN_NAME_FIELDS`.
LATIN_NAME_FIELDS = ("given_name_latin", "middle_name_latin", "family_name_latin", "full_name_latin")

# Same pattern as HOPE's `hope.models.individual.ascii_name_validator`: ASCII letters, with
# single spaces, hyphens or apostrophes allowed as separators between letter groups.
LATIN_NAME_RE = re.compile(r"^[A-Za-z]+(?:[ '-][A-Za-z]+)*$")

LATIN_NAME_INVALID_MESSAGE = "Only ASCII letters, spaces, hyphens, and apostrophes are allowed."


def normalize_latin_name(value: str) -> str:
    """Strip and collapse any whitespace run to a single space.

    Mirrors HOPE's `hope.models.individual.normalize_latin_name`, so that a value accepted here
    is validated and stored the same way once pushed to HOPE.
    """
    if not value:
        return value
    return " ".join(str(value).split())


class LatinNameField(forms.CharField):
    """Optional Latin-spelling name field.

    No transliteration or other processing is applied besides whitespace normalization: the
    value is stored exactly as provided by the source, or left empty when not provided.
    """

    def clean(self, value: str) -> str:
        value = super().clean(value)
        if value:
            value = normalize_latin_name(value)
            if not LATIN_NAME_RE.match(value):
                raise forms.ValidationError(LATIN_NAME_INVALID_MESSAGE, code="invalid_name")

        return value
