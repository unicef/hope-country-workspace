from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from testutils.factories import FlexFieldFileFactory

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp
    from country_workspace.models import FlexFieldFile, User

PNG = b"\x89PNG\r\n\x1a\nimage-bytes"


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


@pytest.fixture
def image_file() -> "FlexFieldFile":
    return FlexFieldFileFactory(content=PNG, mimetype="image/png", original_filename="photo.png")


def test_content_view_serves_file_in_sandbox(app: "CWTestApp", image_file: "FlexFieldFile"):
    response = app.get(reverse("admin:country_workspace_flexfieldfile_content", args=[image_file.pk]))

    assert response.body == PNG
    assert response.headers["Content-Type"] == "image/png"
    assert response.headers["Content-Security-Policy"].startswith("sandbox")
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_content_view_unknown_file_returns_404(app: "CWTestApp", image_file: "FlexFieldFile"):
    image_file.delete()

    app.get(reverse("admin:country_workspace_flexfieldfile_content", args=[image_file.pk]), status=404)


def test_change_view_shows_image_preview(app: "CWTestApp", image_file: "FlexFieldFile"):
    content_url = reverse("admin:country_workspace_flexfieldfile_content", args=[image_file.pk])

    response = app.get(reverse("admin:country_workspace_flexfieldfile_change", args=[image_file.pk]))

    assert f'<img src="{content_url}"' in response.text
