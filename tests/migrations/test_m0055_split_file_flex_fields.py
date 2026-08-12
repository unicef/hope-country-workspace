from __future__ import annotations

from dataclasses import dataclass
import importlib
from types import SimpleNamespace

from django import forms

migration = importlib.import_module("country_workspace.migrations.0061_split_file_flex_fields")


@dataclass
class _Definition:
    id: int
    field_type: object


@dataclass
class _FlexField:
    fieldset_id: int
    name: str
    definition_id: int


@dataclass
class _CheckerFieldset:
    checker_id: int
    fieldset_id: int
    prefix: str


@dataclass
class _Fieldset:
    id: int
    extends_id: int | None


class _Manager:
    def __init__(self, rows: list[object]):
        self._rows = rows

    def only(self, *_args, **_kwargs) -> _Manager:
        return self

    def filter(self, **kwargs) -> _Manager:
        if "definition_id__in" not in kwargs:
            return self
        allowed = set(kwargs["definition_id__in"])
        rows = [row for row in self._rows if getattr(row, "definition_id", None) in allowed]
        return _Manager(rows)

    def iterator(self):
        return iter(self._rows)


def _fake_apps(models_by_name: dict[tuple[str, str], object]):
    return SimpleNamespace(get_model=lambda app, model: models_by_name[(app, model)])


def test_is_file_field_type_matches_runtime_behavior() -> None:
    assert migration._is_file_field_type(forms.FileField) is True
    assert migration._is_file_field_type(forms.ImageField) is True
    assert migration._is_file_field_type(forms.CharField) is False
    assert migration._is_file_field_type("django.forms.fields.FileField") is True


def test_checker_file_field_names_handles_extends_and_template_prefix() -> None:
    FieldDefinition = SimpleNamespace(
        objects=_Manager(
            [
                _Definition(id=1, field_type=forms.FileField),
                _Definition(id=2, field_type=forms.CharField),
            ]
        )
    )
    FlexField = SimpleNamespace(
        objects=_Manager(
            [
                _FlexField(fieldset_id=1, name="photo", definition_id=1),
                _FlexField(fieldset_id=1, name="document", definition_id=1),
                # Override inherited `photo` with text field in extended fieldset.
                _FlexField(fieldset_id=2, name="photo", definition_id=2),
                _FlexField(fieldset_id=2, name="avatar", definition_id=1),
            ]
        )
    )
    Fieldset = SimpleNamespace(
        objects=_Manager(
            [
                _Fieldset(id=1, extends_id=None),
                _Fieldset(id=2, extends_id=1),
            ]
        )
    )
    DataCheckerFieldset = SimpleNamespace(
        objects=_Manager(
            [
                _CheckerFieldset(checker_id=10, fieldset_id=1, prefix="national_id_%s"),
                _CheckerFieldset(checker_id=11, fieldset_id=2, prefix="member_"),
            ]
        )
    )
    apps = _fake_apps(
        {
            ("hope_flex_fields", "FieldDefinition"): FieldDefinition,
            ("hope_flex_fields", "FlexField"): FlexField,
            ("hope_flex_fields", "Fieldset"): Fieldset,
            ("hope_flex_fields", "DataCheckerFieldset"): DataCheckerFieldset,
        }
    )

    result = migration._checker_file_field_names(apps)

    assert result[10] == {"national_id_photo", "national_id_document"}
    # `member_photo` is excluded because local text field overrides inherited file field.
    assert result[11] == {"member_document", "member_avatar"}
