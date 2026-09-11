import pytest
from django import forms

from country_workspace.utils.flex_fields import FlexImageField


@pytest.fixture
def photo_checker():
    """A checker with one image field next to a text field."""
    from testutils.factories import DataCheckerFactory

    return DataCheckerFactory(fields=[("photo", FlexImageField), ("family_name", forms.CharField)])
