from collections.abc import Callable, Iterable
from typing import Any, NamedTuple, Final

import json
from random import Random
from datetime import date, datetime, UTC
from io import BytesIO
from enum import StrEnum
from PIL import Image
from functools import partial

from django.core.files.storage import default_storage
from django.forms import BooleanField

from hope_flex_fields.models import DataChecker
from hope_flex_fields.forms import FlexForm

from faker import Faker
from xlsxwriter import Workbook
from country_workspace.contrib.hope.constants import (
    HOUSEHOLD_CHECKER_NAME,
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)
from country_workspace.state import state
from country_workspace.models import Office
from xlsxwriter.worksheet import Worksheet


type FieldGen = Callable[[Faker, Random], Any]


class GenerationMode(StrEnum):
    HH_IND = "households and individuals"
    PEOPLE = "people"

    def get_sheets(
        self, config: "GeneratorConfig", gen_data: Callable, rng: Random
    ) -> list[tuple["SheetSpec", list[dict]]]:
        """Return list of (spec, data) tuples for this mode."""
        if self == GenerationMode.HH_IND:
            hh_form = get_form(HOUSEHOLD_CHECKER_NAME, config.office_slug)
            ind_form = get_form(INDIVIDUAL_CHECKER_NAME, config.office_slug)
            households = gen_data(generate_households_data)(hh_form)
            individuals = gen_data(generate_individuals_data)(households, ind_form)
            update_collectors(households, len(individuals), rng)
            return [(HOUSEHOLDS_SPEC, households), (INDIVIDUALS_SPEC, individuals)]
        if self == GenerationMode.PEOPLE:
            people_form = get_form(PEOPLE_CHECKER_NAME, config.office_slug)
            people = gen_data(generate_people_data)(people_form)
            return [(PEOPLE_SPEC, people)]
        raise ValueError(f"Unknown generation mode: {self}")


class GeneratorConfig(NamedTuple):
    mode: GenerationMode = GenerationMode.HH_IND
    office_slug: str = "afghanistan"
    locale: str = "en"
    hh_amount: int = 5
    inds_per_hh: tuple[int, int] = (3, 7)
    people: int = 20
    filename: str = "rdi_generated.xlsx"
    seed: int | None = None
    # these fields will be excluded by base name from sheet
    exclude_fields: tuple[str, ...] = ()


class SheetName(StrEnum):
    HOUSEHOLDS = "Households"
    INDIVIDUALS = "Individuals"
    PEOPLE = "People"


class SheetSpec(NamedTuple):
    name: "SheetName"
    prefix: str = ""
    postfix: str = ""
    plain_fields: tuple[str, ...] = ()
    id_key: str | None = None
    parent_id_key: str | None = None
    exclude_from_export: tuple[str, ...] = ()

    def get_fields(self, row: dict) -> list[str]:
        """Extract field names from row, respecting exclude_from_export."""
        if self.exclude_from_export:
            return [f for f in row if f not in self.exclude_from_export]
        return list(row.keys())


HOUSEHOLDS_SPEC = SheetSpec(
    name=SheetName.HOUSEHOLDS,
    postfix="_h_c",
    plain_fields=("household_id", "head_of_household", "primary_collector", "alternate_collector"),
    id_key="household_id",
    parent_id_key=None,
    exclude_from_export=("individuals_start", "individuals_count"),
)

INDIVIDUALS_SPEC = SheetSpec(
    name=SheetName.INDIVIDUALS,
    postfix="_i_c",
    plain_fields=("individual_id", "household_id"),
    id_key="individual_id",
    parent_id_key="household_id",
)

PEOPLE_SPEC = SheetSpec(
    name=SheetName.PEOPLE,
    prefix="pp_",
    postfix="_i_c",
    id_key="index_id",
)

SHEETS_BY_NAME: dict[SheetName, SheetSpec] = {
    HOUSEHOLDS_SPEC.name: HOUSEHOLDS_SPEC,
    INDIVIDUALS_SPEC.name: INDIVIDUALS_SPEC,
    PEOPLE_SPEC.name: PEOPLE_SPEC,
}


PROTECTED_FIELDS: Final[dict[SheetName, tuple[str, ...]]] = {
    SheetName.HOUSEHOLDS: (HOUSEHOLDS_SPEC.id_key,),
    SheetName.INDIVIDUALS: (INDIVIDUALS_SPEC.id_key, INDIVIDUALS_SPEC.parent_id_key),
    SheetName.PEOPLE: (PEOPLE_SPEC.id_key,),
}

KNOWN_PREFIXES: Final[tuple[str, ...]] = tuple(
    sorted((spec.prefix.lower() for spec in SHEETS_BY_NAME.values()), key=len, reverse=True)
)

KNOWN_POSTFIXES: Final[tuple[str, ...]] = tuple(
    sorted((spec.postfix.lower() for spec in SHEETS_BY_NAME.values()), key=len, reverse=True)
)

NAME_FIELD_KEYS = ("given_name", "family_name", "middle_name", "full_name")

FIELD_PATTERNS: dict[str, FieldGen] = {
    "address": lambda fake, _rng, /: fake.street_address(),
    "phone_no": lambda fake, _rng, /: _generate_phone_e164(rng=_rng),
    "birth_date": lambda fake, _rng, /: fake.date_between(start_date="-50y", end_date="-1y"),
    "estimated_birth_date": lambda _fake, rng, /: bool(rng.getrandbits(1)),
    "consent": lambda _fake, rng, /: bool(rng.getrandbits(1)),
    "photo": lambda _fake, rng, /: _generate_png_solid_square(rng=rng),
}

FIELDSET_PREFIXES = {
    "document": ("national_id_", "national_passport_", "birth_certificate_"),
    "account": ("mobile_", "bank_", "cash_"),
}

FIELDSET_PREFIXES_PATTERNS: dict[tuple[str, ...], dict[str, FieldGen]] = {
    FIELDSET_PREFIXES["document"]: {
        "document_number": lambda fake, _rng, /: fake.bothify("???-########"),
        "issuance_date": lambda fake, _rng, /: fake.date_between(start_date="-15y", end_date="-1y"),
        "expiry_date": lambda fake, _rng, /: fake.date_between(start_date="today", end_date="+10y"),
        "image": lambda _fake, rng, /: _generate_png_solid_square(rng=rng),
    },
    FIELDSET_PREFIXES["account"]: {
        "number": lambda fake, _rng, /: fake.bothify("???-########"),
        "data": lambda fake, rng, /: _generate_json_data(fake, rng),
    },
}


def _colname(spec: SheetSpec, field_name: str) -> str:
    """Return the column name using the sheet postfix unless it is an id/parent id key."""
    if field_name in {spec.id_key, spec.parent_id_key}:
        return f"{spec.prefix}{field_name}" if spec.prefix else field_name
    return f"{spec.prefix}{field_name}{spec.postfix}"


def _generate_json_data(fake: Faker, rng: Random) -> Any:
    if (k := rng.randint(0, 3)) == 0:
        return None
    return json.dumps({fake.word(): fake.word() for _ in range(k)}, ensure_ascii=False)


def _generate_png_solid_square(side: int = 50, *, rng: Random) -> bytes | None:
    if rng.getrandbits(1):
        return None
    # solid RGB color rectangle (square) of the requested side
    color = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
    img = Image.new("RGB", (side, side), color)
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _generate_name_parts(fake: Faker) -> dict[str, str]:
    parts = fake.name().split()
    return {
        "given_name": parts[0] if parts else fake.first_name(),
        "middle_name": parts[1] if len(parts) >= 3 else "",
        "family_name": parts[-1] if len(parts) >= 2 else fake.last_name(),
        "full_name": " ".join(parts) if parts else fake.name(),
    }


def _generate_phone_e164(*, rng: Random) -> str:
    return f"+1202555{rng.randint(1000, 9999):04d}"


def _is_demographic_counter(name: str) -> bool:
    return name == "pregnant_count" or (
        name.startswith(("female_age_group_", "male_age_group_")) and name.endswith(("_count", "_disabled_count"))
    )


def _strip_known_postfix(name: str) -> str:
    """Remove any known sheet postfix from the provided field name."""
    for p in KNOWN_POSTFIXES:
        if name.lower().endswith(p):
            return name[: -len(p)]
    return name


def _effective_exclude(field_names: Iterable[str], exclude_fields: Iterable[str], sheet: SheetName) -> list[str]:
    """Exclude fields by base name for the sheet, preserving protected IDs and order."""
    exclude = {_strip_known_postfix(n) for n in exclude_fields}
    exclude -= {n for n in PROTECTED_FIELDS.get(sheet, ()) if n}
    return [name for name in field_names if _strip_known_postfix(name) not in exclude]


def get_form(dc_name: str, office_slug: str) -> FlexForm:
    """Instantiate a FlexForm for the given DataChecker within the Office tenant context."""
    dc = DataChecker.objects.get(name=dc_name)
    office = Office.objects.get(slug=office_slug)
    with state.set(tenant=office):
        form_class = dc.get_form_class()
    return form_class(prefix="flex_field")


def pick_from_choices(field: Any, rng: Random) -> Any:
    if not (choices := getattr(field, "choices", ())):
        return bool(rng.getrandbits(1)) if isinstance(field, BooleanField) else None

    non_empty = [v for v, _ in choices if v not in ("", None)]

    if getattr(getattr(field, "widget", None), "allow_multiple_selected", False):
        if not non_empty:
            return None
        count = rng.randint(1, min(3, len(non_empty)))
        return ", ".join(map(str, rng.sample(non_empty, count)))

    return rng.choice(non_empty) if non_empty else None


def _fake_value(field_name: str, fake: Faker, field_patterns: dict[str, FieldGen], rng: Random) -> Any:
    base = _strip_known_postfix(field_name.lower())

    if base in field_patterns:
        return field_patterns[base](fake, rng)

    for prefixes, mapping in FIELDSET_PREFIXES_PATTERNS.items():
        for prefix in prefixes:
            if base.startswith(prefix):
                tail = base[len(prefix) :]
                if tail in mapping:
                    return mapping[tail](fake, rng)

    return None


def resolve_field_value(field_name: str, django_field: Any, fake: Faker, rng: Random) -> Any:
    v = pick_from_choices(django_field, rng)
    if v is not None:
        return v
    return _fake_value(field_name, fake, FIELD_PATTERNS, rng)


def _get_sheet_specific_handler(name: str, sheet_type: SheetName, rng: Random) -> Callable | None:
    """Return sheet-specific handler or None."""
    spec = SHEETS_BY_NAME[sheet_type]
    if sheet_type is SheetName.INDIVIDUALS:
        if name == spec.id_key:
            return lambda ind_id, _hh_id, **_: ind_id
        if name == spec.parent_id_key:
            return lambda _ind_id, hh_id, **_: hh_id
    elif sheet_type is SheetName.HOUSEHOLDS:
        if name in spec.plain_fields:
            return lambda **_: None
        if _is_demographic_counter(name):
            return lambda **_: rng.choice((None, 1, 2, 3))
    elif sheet_type is SheetName.PEOPLE:
        if name == spec.id_key:
            return lambda index, **_: index
    return None


def make_field_writers(
    fields: list[str],
    sheet_type: SheetName,
    form: FlexForm,
    fake: Faker,
    rng: Random,
) -> list[Callable[..., Any]]:
    """Build per-column writer callables for the given sheet based on the form schema."""

    def writer_for(name: str) -> Callable:
        if handler := _get_sheet_specific_handler(name, sheet_type, rng):
            return handler
        if name in NAME_FIELD_KEYS:
            return lambda *_, name_parts=None, **__: name_parts.get(name, "") if name_parts else ""
        field = form.base_fields[name]
        return lambda *_, f=field, n=name, **__: resolve_field_value(n, f, fake, rng)

    return [writer_for(n) for n in fields]


def generate_individuals_data(
    households: list[dict], ind_form: FlexForm, config: GeneratorConfig, fake: Faker, rng: Random
) -> list[dict]:
    individuals: list[dict] = []
    ind_fields = _effective_exclude(ind_form.base_fields.keys(), config.exclude_fields, SheetName.INDIVIDUALS)
    ind_writers = make_field_writers(ind_fields, SheetName.INDIVIDUALS, ind_form, fake, rng)

    for hh_data in households:
        hh_id = hh_data["household_id"]
        start_ind = hh_data["individuals_start"]
        ind_count = hh_data["individuals_count"]

        for i in range(ind_count):
            ind_id = start_ind + i
            name_parts = _generate_name_parts(fake)
            ind_data = {
                field_name: ind_writers[j](ind_id, hh_id, name_parts=name_parts)
                for j, field_name in enumerate(ind_fields)
            }
            individuals.append(ind_data)

    return individuals


def generate_people_data(pp_form: FlexForm, config: GeneratorConfig, fake: Faker, rng: Random) -> list[dict]:
    people: list[dict] = []
    pp_fields = _effective_exclude(pp_form.base_fields.keys(), config.exclude_fields, SheetName.PEOPLE)
    pp_writers = make_field_writers(pp_fields, SheetName.PEOPLE, pp_form, fake, rng)

    for ppl_index in range(1, config.people + 1):
        name_parts = _generate_name_parts(fake)
        pp_data = {
            field_name: pp_writers[i](index=ppl_index, name_parts=name_parts) for i, field_name in enumerate(pp_fields)
        }
        pp_data["index_id"] = ppl_index
        people.append(pp_data)

    return people


def generate_households_data(hh_form: FlexForm, config: GeneratorConfig, fake: Faker, rng: Random) -> list[dict]:
    hh_fields = _effective_exclude(hh_form.base_fields.keys(), config.exclude_fields, SheetName.HOUSEHOLDS)
    hh_writers = make_field_writers(hh_fields, SheetName.HOUSEHOLDS, hh_form, fake, rng)

    households = []
    ind_counter = 1

    for hh_id in range(1, config.hh_amount + 1):
        individuals_count = rng.randint(*config.inds_per_hh)
        name_parts = _generate_name_parts(fake)
        hh_data = {field_name: hh_writers[i](name_parts=name_parts) for i, field_name in enumerate(hh_fields)}
        hh_data.update(
            {
                "household_id": hh_id,
                "size": individuals_count,
                "head_of_household": ind_counter + rng.randint(0, individuals_count - 1),
                "individuals_start": ind_counter,
                "individuals_count": individuals_count,
            }
        )
        households.append(hh_data)
        ind_counter += individuals_count

    return households


def update_collectors(households: list[dict], total_individuals: int, rng: Random) -> None:
    if not total_individuals:
        return

    for hh_data in households:
        if "primary_collector" in hh_data:
            hh_data["primary_collector"] = rng.randint(1, total_individuals)

        if "alternate_collector" in hh_data:
            primary = hh_data.get("primary_collector")
            if total_individuals >= 2 and rng.randint(0, 1) == 1:
                alt = rng.randint(1, total_individuals - 1)
                hh_data["alternate_collector"] = alt if (primary is None or alt < primary) else alt + 1
            else:
                hh_data["alternate_collector"] = None


def write_cell(ws: "Worksheet", row: int, col: int, value: Any, *, date_fmt: Any) -> None:
    """Write a value as date/image/primitive depending on its runtime type."""
    if isinstance(value, date):
        ws.write_datetime(row, col, datetime(value.year, value.month, value.day, tzinfo=UTC), date_fmt)
        return
    if isinstance(value, bytes | bytearray):
        ws.insert_image(
            row, col, f"image_{row}_{col}.png", {"image_data": BytesIO(value), "x_scale": 0.5, "y_scale": 0.5}
        )
        return
    ws.write(row, col, value)


def write_row(
    ws: "Worksheet",
    fields: list[str],
    rows: list[dict[str, object]],
    *,
    cell_writer: Callable[[Worksheet, int, int, Any], None],
) -> None:
    """Write records to a worksheet by field order, starting at row index 2."""
    for r, row in enumerate(rows, start=2):
        get = row.get
        for c, name in enumerate(fields):
            cell_writer(ws, r, c, get(name))


def write_excel(sheets: list[tuple[SheetSpec, list[dict]]], filename: str) -> None:
    """Write sheets to Excel."""
    sheets = [(spec, rows) for spec, rows in sheets if rows]
    if not sheets:
        return

    buff = BytesIO()
    with Workbook(buff, {"in_memory": True, "use_zip64": True, "remove_timezone": True}) as wb:
        date_fmt = wb.add_format({"num_format": "yyyy-mm-dd"})
        cell_writer = partial(write_cell, date_fmt=date_fmt)

        for spec, rows in sheets:
            fields = spec.get_fields(rows[0])
            ws = wb.add_worksheet(spec.name.value)
            ws.write_row(0, 0, [_colname(spec, f) for f in fields])
            write_row(ws, fields, rows, cell_writer=cell_writer)

    buff.seek(0)
    with default_storage.open(filename, "wb") as f:
        f.write(buff.getbuffer())


def generate(config: GeneratorConfig = None) -> None:
    if config is None:
        config = GeneratorConfig()

    rng = Random(config.seed)  # noqa: S311
    fake = Faker(config.locale)
    if config.seed is not None:
        fake.seed_instance(config.seed)

    gen_data = partial(partial, config=config, fake=fake, rng=rng)
    sheets = config.mode.get_sheets(config, gen_data, rng)
    write_excel(sheets, config.filename)
