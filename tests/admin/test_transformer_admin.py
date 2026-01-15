import json
import pytest
from django.contrib.admin import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory

from country_workspace.admin.transformer import TransformerAdmin, TransformerTestForm
from country_workspace.models import Transformer
from testutils.factories import SuperUserFactory, TransformerFactory


def _request_with_messages(rf: RequestFactory, user):
    request = rf.post("/")
    request.user = user
    middleware = SessionMiddleware(lambda x: HttpResponse())
    middleware.process_request(request)
    request.session.save()
    request._messages = FallbackStorage(request)  # type: ignore[attr-defined]
    return request


@pytest.mark.django_db
def test_transformer_test_form_valid_json():
    form = TransformerTestForm(data={"code": "x", "record": '{"a":1}'})
    assert form.is_valid()
    assert form.cleaned_data["record"] == {"a": 1}


@pytest.mark.django_db
def test_transformer_test_form_invalid_json():
    form = TransformerTestForm(data={"code": "x", "record": "not json"})
    assert not form.is_valid()
    assert "Invalid JSON" in form.errors["record"][0]


@pytest.mark.django_db
def test_formatted_value_transformations_renders_pre():
    obj = TransformerFactory(value_transformations="line1\nline2")
    admin = TransformerAdmin(Transformer, AdminSite())
    html = admin.formatted_value_transformations(obj)
    assert "<pre" in html
    assert "line1" in html
    assert "line2" in html


@pytest.mark.django_db
def test_edit_and_verify_save_updates_code(rf: RequestFactory):
    user = SuperUserFactory()
    obj = TransformerFactory(value_transformations="old")
    admin = TransformerAdmin(Transformer, AdminSite())
    request = _request_with_messages(rf, user)
    request.POST = request.POST.copy()  # type: ignore[assignment]
    request.POST.update({"code": "new code", "record": "{}", "action": "save"})

    admin.edit_and_verify(request, str(obj.pk))  # type: ignore[misc]

    obj.refresh_from_db()
    assert obj.value_transformations == "new code"


@pytest.mark.django_db
def test_edit_and_verify_verify_does_not_persist_code(rf: RequestFactory, mocker):
    user = SuperUserFactory()
    obj = TransformerFactory(value_transformations="persisted")
    admin = TransformerAdmin(Transformer, AdminSite())
    request = _request_with_messages(rf, user)
    request.POST = request.POST.copy()  # type: ignore[assignment]
    request.POST.update({"code": "temp", "record": json.dumps({"foo": "bar"}), "action": "verify"})

    apply_mock = mocker.patch.object(Transformer, "apply", return_value={"foo": "baz"})

    admin.edit_and_verify(request, str(obj.pk))  # type: ignore[misc]
    obj.refresh_from_db()

    # verify uses provided code but does not persist it
    assert obj.value_transformations == "persisted"
    apply_mock.assert_called_once()
