import pytest
import re
import json
import random

from collections.abc import Callable
from datetime import date
from uuid import uuid4
from faker import Faker
from io import BytesIO
from pathlib import Path

from django import forms
from PIL import Image
from pytest_mock import MockerFixture
from contextlib import nullcontext
import country_workspace.utils.gen_rdi as rdi


# ---------- fixtures ----------


@pytest.fixture
def rng() -> random.Random:
    return random.Random(123)


@pytest.fixture
def fake() -> Faker:
    f = Faker("en")
    f.seed_instance(123)
    return f


@pytest.fixture
def flexform_factory() -> Callable[[dict[str, forms.Field]], forms.Form]:
    def _make(fields: dict[str, forms.Field], *, prefix: str = "flex_field") -> forms.Form:
        form_class = type(f"FlexFormStub_{uuid4().hex}", (forms.Form,), dict(fields))
        return form_class(prefix=prefix)

    return _make


@pytest.fixture
def image_file_factory(tmp_path: Path) -> Callable[..., Path]:
    def _make(name: str = "image.png", *, valid: bool = True) -> Path:
        path = tmp_path / name
        if valid:
            Image.new("RGB", (1, 1), (255, 0, 0)).save(path, format="PNG")
        else:
            path.write_text("not an image")
        return path

    return _make


# ---------- column spec / naming / exclude ----------


def test_sheet_spec_get_fields_excludes_runtime() -> None:
    spec = rdi.SheetSpec(
        name=rdi.SheetName.HOUSEHOLDS,
        exclude_from_export=("individuals_start", "individuals_count"),
    )
    row = {"a": 1, "individuals_start": 10, "b": 2, "individuals_count": 3}
    assert spec.get_fields(row) == ["a", "b"]  # excluded runtime fields


def test__colname_prefix_postfix_and_ids() -> None:
    spec = rdi.PEOPLE_SPEC  # prefix="pp_", postfix="_i_c", id_key="index_id"
    assert rdi._colname(spec, "index_id") == "pp_index_id"  # special case for ID field
    assert rdi._colname(spec, "given_name") == "pp_given_name_i_c"  # general case
    assert rdi._colname(spec, "given_name", with_postfix=False) == "pp_given_name"  # no-postfix mode


def test__effective_exclude_respects_protected_ids() -> None:
    names = ["index_id", "pp_given_name_i_c", "pp_wallet_address_i_c"]
    out = rdi._effective_exclude(names, exclude_fields=["index_id", "wallet_address"], sheet=rdi.SheetName.PEOPLE)
    # protected id (index_id) is kept, wallet_address is excluded
    assert out == ["index_id", "pp_given_name_i_c"]


# ---------- choices / resolve / writers ----------


def test_pick_from_choices_single_and_multi(rng: random.Random) -> None:
    # single
    fld = forms.ChoiceField(choices=[("", "—"), ("A", "A"), ("B", "B")])
    v = rdi.pick_from_choices(fld, rng)
    assert v in {"A", "B"}
    # multi
    fld_multi = forms.MultipleChoiceField(choices=[("x", "x"), ("y", "y"), ("z", "z")])
    v2 = rdi.pick_from_choices(fld_multi, rng)
    assert isinstance(v2, str)
    assert len(v2) >= 1


def test_resolve_field_value_prefers_choices_over_patterns(fake: Faker, rng: random.Random) -> None:
    fld = forms.BooleanField(required=False)
    # choices handler must be preferred over BooleanField pattern
    got = rdi.resolve_field_value("consent_i_c", fld, fake, rng)
    assert got in {True, False}


def test_resolve_field_value_uses_disk_image_iter(
    fake: Faker,
    rng: random.Random,
    image_file_factory: Callable[..., Path],
) -> None:
    field = forms.CharField(required=False)
    image = image_file_factory()

    got = rdi.resolve_field_value("photo_i_c", field, fake, rng, iter([image]))

    assert got == image


def test_make_field_writers_special_handlers_for_ids(
    fake: Faker, rng: random.Random, flexform_factory: Callable[[dict[str, forms.Field]], forms.Form]
) -> None:
    # Individuals: individual_id and household_id have special handlers
    fields = ["individual_id", "household_id", "given_name"]
    form = flexform_factory({k: forms.CharField(required=False) for k in fields})
    writers = rdi.make_field_writers(fields, rdi.SheetName.INDIVIDUALS, form, fake, rng)

    row = {
        fields[0]: writers[0](123, 7, name_parts=None),
        fields[1]: writers[1](123, 7, name_parts=None),
        fields[2]: writers[2](123, 7, name_parts={"given_name": "John"}),
    }
    assert row["individual_id"] == 123
    assert row["household_id"] == 7
    assert row["given_name"] == "John"


def test_make_field_writers_none_field_returns_noop(fake: Faker, rng: random.Random) -> None:
    """Returns noop when form.base_fields[name] is None."""
    import country_workspace.utils.gen_rdi as rdi

    form = type("Stub", (), {"base_fields": {"ghost_field": None}})()
    writers = rdi.make_field_writers(["ghost_field"], rdi.SheetName.PEOPLE, form, fake, rng)
    assert callable(writers[0])
    assert writers[0]() is None


# ---------- sheet-specific handlers ----------


def test__get_sheet_specific_handler_count_branch(rng: random.Random) -> None:
    """HOUSEHOLDS: *_count should return a callable producing None|1|2|3."""
    h = rdi._get_sheet_specific_handler("individuals_count", rdi.SheetName.HOUSEHOLDS, rng)
    assert callable(h)
    vals = {h()} | {h()} | {h()}
    assert vals.issubset({None, 1, 2, 3})


# ---------- data generation (people / hh+ind) ----------


def test_generate_people_data_basic(
    fake: Faker, rng: random.Random, flexform_factory: Callable[[dict[str, forms.Field]], forms.Form]
) -> None:
    fields = {"index_id": forms.IntegerField(), "pp_given_name_i_c": forms.CharField(required=False)}
    pp_form = flexform_factory(fields)
    cfg = rdi.GeneratorConfig(mode=rdi.GenerationMode.PEOPLE, people=3)
    rows = rdi.generate_people_data(pp_form, cfg, fake, rng)
    assert [r["index_id"] for r in rows] == [1, 2, 3]
    assert len(rows) == 3


def test_generate_households_and_individuals_linkage(
    fake: Faker, rng: random.Random, flexform_factory: Callable[[dict[str, forms.Field]], forms.Form]
) -> None:
    hh_fields = {
        "household_id": forms.IntegerField(),
        "head_of_household_id": forms.IntegerField(required=False),
        "size": forms.IntegerField(required=False),
    }
    ind_fields = {"individual_id": forms.IntegerField(), "household_id": forms.IntegerField()}
    hh_form = flexform_factory(hh_fields)
    ind_form = flexform_factory(ind_fields)

    cfg = rdi.GeneratorConfig(mode=rdi.GenerationMode.HH_IND, hh_amount=2, inds_per_hh=(2, 2))
    households = rdi.generate_households_data(hh_form, cfg, fake, rng)
    individuals = rdi.generate_individuals_data(households, ind_form, cfg, fake, rng)

    assert households[0]["household_id"] == 1
    assert households[1]["household_id"] == 2
    h1_inds = [row for row in individuals if row["household_id"] == 1]
    h2_inds = [row for row in individuals if row["household_id"] == 2]
    assert len(h1_inds) == 2
    assert len(h2_inds) == 2


# ---------- collectors ----------


def test_update_collectors_primary_and_alternate_valid(rng: random.Random) -> None:
    households = [{"primary_collector_id": None, "alternate_collector_id": None} for _ in range(3)]
    rdi.update_collectors(households, total_individuals=10, rng=rng)
    for hh in households:
        # primary in 1..total
        assert 1 <= hh["primary_collector_id"] <= 10
        # alternate either None or != primary and in range 1..total
        alt = hh["alternate_collector_id"]
        assert (alt is None) or (1 <= alt <= 10 and alt != hh["primary_collector_id"])


def test_update_collectors_no_total_keeps_households_intact(rng: random.Random) -> None:
    households = [{"primary_collector_id": None, "alternate_collector_id": None} for _ in range(2)]
    snapshot = [h.copy() for h in households]
    rdi.update_collectors(households, total_individuals=0, rng=rng)
    assert households == snapshot  # no changes


def test_update_collectors_sets_alternate_none_when_total_lt_2(rng: random.Random) -> None:
    households = [{"primary_collector_id": None, "alternate_collector_id": None} for _ in range(3)]
    rdi.update_collectors(households, total_individuals=1, rng=rng)
    for hh in households:
        assert hh["primary_collector_id"] == 1  # only possible pick in [1..1]
        assert hh["alternate_collector_id"] is None  # branch: total_individuals >= 2 is False


# ---------- writing (cell/row/excel) ----------


def test_write_cell_writes_date_and_bytes(mocker: MockerFixture) -> None:
    ws = mocker.MagicMock()
    dt = date(2020, 5, 6)
    # date → write_datetime with UTC
    rdi.write_cell(ws, 1, 2, dt, date_fmt="FMT")
    ws.write_datetime.assert_called_once()
    # bytes → insert_image
    ws.reset_mock()
    rdi.write_cell(ws, 0, 0, b"\x89PNG", date_fmt="FMT")
    ws.insert_image.assert_called_once()
    # str → write
    ws.reset_mock()
    rdi.write_cell(ws, 0, 0, "x", date_fmt="FMT")
    ws.write.assert_called_once()


def test_write_cell_writes_path_image(
    mocker: MockerFixture,
    image_file_factory: Callable[..., Path],
) -> None:
    ws = mocker.MagicMock()
    image = image_file_factory()

    rdi.write_cell(ws, 1, 2, image, date_fmt="FMT")

    ws.insert_image.assert_called_once_with(1, 2, str(image), {"x_scale": 0.5, "y_scale": 0.5})


def test_write_row_calls_cell_writer_in_field_order(mocker: MockerFixture) -> None:
    ws = mocker.MagicMock()
    fields = ["a", "b"]
    rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    cw = mocker.MagicMock()
    rdi.write_row(ws, fields, rows, cell_writer=cw)
    # 2 rows * 2 fields = 4 calls
    assert cw.call_count == 4


def test_write_excel_skips_empty_and_persists_file(mocker: MockerFixture) -> None:
    """Non-empty sheets → storage.open is used."""
    m_open = mocker.patch.object(rdi.default_storage, "open")
    m_open.return_value.__enter__.return_value = BytesIO()
    mocker.patch.object(rdi, "Workbook")
    spec = rdi.PEOPLE_SPEC
    sheets = [(spec, [{"index_id": 1, "pp_given_name_i_c": "A"}])]
    rdi.write_excel(sheets, filename="file.xlsx")
    m_open.assert_called_once()


def test_write_excel_no_sheets_exits_early(mocker: MockerFixture) -> None:
    """No sheets → no Workbook/IO calls."""
    wb = mocker.patch.object(rdi, "Workbook")
    storage = mocker.patch.object(rdi, "default_storage")
    rdi.write_excel([], filename="x.xlsx")
    wb.assert_not_called()
    storage.open.assert_not_called()


# ---------- primitive generators (json/png/phone/disk images) ----------


def test__generate_json_data_none(fake: Faker, rng: random.Random, mocker: MockerFixture) -> None:
    """Returns None when randint picks 0."""
    mocker.patch.object(rng, "randint", return_value=0)
    assert rdi._generate_json_data(fake, rng) is None


def test__generate_json_data_object(fake: Faker, rng: random.Random, mocker: MockerFixture) -> None:
    """Returns JSON string with k key/value pairs when k>0."""
    mocker.patch.object(rng, "randint", return_value=2)
    mocker.patch.object(fake, "word", side_effect=["k1", "v1", "k2", "v2"])  # ensure unique keys
    out = rdi._generate_json_data(fake, rng)
    data = json.loads(out)
    assert data == {"k1": "v1", "k2": "v2"}


def test__generate_png_solid_square_none(rng: random.Random, mocker: MockerFixture) -> None:
    """Returns None when getrandbits signals skip."""
    mocker.patch.object(rng, "getrandbits", return_value=1)
    assert rdi._generate_png_solid_square(rng=rng) is None


def test__generate_png_solid_square_png(rng: random.Random, mocker: MockerFixture) -> None:
    """Returns PNG bytes with a valid header when generated."""
    mocker.patch.object(rng, "getrandbits", return_value=0)
    mocker.patch.object(rng, "randint", side_effect=[10, 20, 30])  # RGB
    blob = rdi._generate_png_solid_square(rng=rng)
    assert isinstance(blob, (bytes, bytearray))
    assert blob.startswith(b"\x89PNG")


def test__generate_phone_e164(rng: random.Random, mocker: MockerFixture) -> None:
    """Formats E.164 with fixed 4-digit tail."""
    mocker.patch.object(rng, "randint", return_value=1234)
    assert rdi._generate_phone_e164(rng=rng) == "+12025551234"


def test__load_disk_images_returns_only_valid_files(image_file_factory: Callable[..., Path]) -> None:
    """Returns sorted readable images only."""
    valid = image_file_factory("a.png")
    image_file_factory("b.txt", valid=False)

    assert rdi._load_disk_images(str(valid.parent)) == (valid,)


def test__load_disk_images_raises_for_missing_dir(tmp_path: Path) -> None:
    """Raises when image directory does not exist."""
    with pytest.raises(ValueError, match="Image directory does not exist"):
        rdi._load_disk_images(str(tmp_path / "missing"))


def test__load_disk_images_raises_when_no_readable_images(image_file_factory: Callable[..., Path]) -> None:
    """Raises when no readable image files are found."""
    invalid = image_file_factory("x.txt", valid=False)

    with pytest.raises(ValueError, match="No readable images found"):
        rdi._load_disk_images(str(invalid.parent))


# ---------- _fake_value patterns ----------


def test__fake_value_field_patterns_nullable_none(fake: Faker, rng: random.Random, mocker: MockerFixture) -> None:
    """Returns None when nullable branch triggers."""
    mocker.patch.object(rng, "random", return_value=0.1)  # < NULLABLE_RATE (0.25)
    assert rdi._fake_value("wallet_address", fake, rdi.FIELD_PATTERNS, rng) is None


def test__fake_value_field_patterns_value(fake: Faker, rng: random.Random, mocker: MockerFixture) -> None:
    """Returns generated value when not nullable."""
    mocker.patch.object(rng, "random", return_value=0.9)
    v = rdi._fake_value("wallet_address", fake, rdi.FIELD_PATTERNS, rng)
    assert isinstance(v, str)
    assert v.startswith("0x")
    assert len(v) >= 42


def test__fake_value_fieldset_prefix_document(fake: Faker, rng: random.Random) -> None:
    """Matches FIELDSET_PREFIXES_PATTERNS for 'document' group."""
    v = rdi._fake_value("national_passport_document_number", fake, rdi.FIELD_PATTERNS, rng)
    assert isinstance(v, str)
    assert v.startswith("DOC-")


def test__fake_value_fieldset_prefix_account_number(fake: Faker, rng: random.Random) -> None:
    """Matches FIELDSET_PREFIXES_PATTERNS for 'account' group."""
    v = rdi._fake_value("mobile_number", fake, rdi.FIELD_PATTERNS, rng)
    assert isinstance(v, str)
    assert v.startswith("ACC-")


def test__fake_value_no_match_returns_none(fake: Faker, rng: random.Random) -> None:
    """Returns None when no pattern/prefix match found."""
    assert rdi._fake_value("some_unknown_field", fake, rdi.FIELD_PATTERNS, rng) is None


# ---------- filename build ----------


@pytest.mark.parametrize(
    ("mode", "expected_token"),
    [
        (rdi.GenerationMode.PEOPLE, "pp5"),  # PEOPLE → pp{people}
        (rdi.GenerationMode.HH_IND, "hh3ind2-4"),  # HH_IND → hh{A}ind{lo}-{hi}
    ],
)
def test__build_filename_composition(mode: rdi.GenerationMode, expected_token: str) -> None:
    cfg = rdi.GeneratorConfig(
        mode=mode,
        office_slug="afghanistan",
        locale="en_US",
        people=5,
        hh_amount=3,
        inds_per_hh=(2, 4),
        seed=42,
        exclude_fields=("a", "b"),
    )
    name = rdi._build_filename(cfg)
    assert name.endswith(".xlsx")
    stem = name[:-5]
    parts = stem.split("_")
    assert parts[0] == "rdi"
    assert parts[1] == "afghanistan"
    assert parts[2] == expected_token
    assert parts[3] == "enUS"
    assert parts[4] == "s42"
    assert parts[5] == "excl2flds"
    assert re.fullmatch(r"\d{14}", parts[6]), "timestamp must be YYYYMMDDhhmmss"


def test__build_filename_includes_img_token() -> None:
    cfg = rdi.GeneratorConfig(image_dir="/tmp/images")
    name = rdi._build_filename(cfg)

    assert "_img_" in name


# ---------- end-to-end generate ----------


def test_generate_end_to_end_calls_pipeline(mocker: MockerFixture) -> None:
    cfg = rdi.GeneratorConfig(mode=rdi.GenerationMode.PEOPLE, people=2, seed=123, filename="X.xlsx")
    spy_sheets = mocker.patch.object(
        rdi.GenerationMode, "get_sheets", return_value=[(rdi.PEOPLE_SPEC, [{"index_id": 1}])]
    )
    spy_write = mocker.patch.object(rdi, "write_excel")
    out = rdi.generate(cfg)
    assert out == "X.xlsx"
    spy_sheets.assert_called_once()
    spy_write.assert_called_once()


def test_generate_defaults_min(mocker: MockerFixture) -> None:
    """generate(None) builds default config and runs the pipeline."""
    mocker.patch.object(rdi.GenerationMode, "get_sheets", return_value=[(rdi.PEOPLE_SPEC, [{"index_id": 1}])])
    w = mocker.patch.object(rdi, "write_excel")
    out = rdi.generate()  # config=None path
    assert re.fullmatch(r"rdi_afghanistan_pp20_en_\d{14}\.xlsx", out)
    rdi.GenerationMode.get_sheets.assert_called_once()
    w.assert_called_once()


def test_generate_loads_images_when_image_dir_is_set(mocker: MockerFixture) -> None:
    """image_dir should trigger disk image loading before sheet generation."""
    cfg = rdi.GeneratorConfig(image_dir="/tmp/images", filename="x.xlsx")
    mocker.patch.object(rdi, "_load_disk_images", return_value=(Path("/tmp/images/a.png"),))
    mocker.patch.object(rdi.GenerationMode, "get_sheets", return_value=[(rdi.PEOPLE_SPEC, [{"index_id": 1}])])
    w = mocker.patch.object(rdi, "write_excel")

    out = rdi.generate(cfg)

    assert out == "x.xlsx"
    rdi._load_disk_images.assert_called_once_with("/tmp/images")
    w.assert_called_once()


# ---------- get_form ----------


def test_get_form_min(mocker: MockerFixture) -> None:
    """Fetch DC & Office, enter tenant ctx, return prefixed Form instance."""
    form_type = type("FlexFormStub", (forms.Form,), {})
    dc_stub = type("DC", (), {"get_form_class": lambda self: form_type})()

    dc_mgr = mocker.Mock(spec=["get"], **{"get.return_value": dc_stub})
    off_mgr = mocker.Mock(spec=["get"], **{"get.return_value": object()})

    mocker.patch.object(rdi.DataChecker, "objects", dc_mgr)
    mocker.patch.object(rdi.Office, "objects", off_mgr)
    mocker.patch.object(rdi.state, "set", side_effect=lambda **_: nullcontext())

    form = rdi.get_form(dc_name="PEOPLE_CHECKER", office_slug="afghanistan")

    assert isinstance(form, form_type)
    assert form.prefix == "flex_field"


# ---------- GenerationMode.get_sheets ----------


@pytest.mark.parametrize(
    ("mode", "is_people"),
    [
        (rdi.GenerationMode.PEOPLE, True),
        (rdi.GenerationMode.HH_IND, False),
    ],
)
def test_generation_mode_get_sheets_min(
    mocker: MockerFixture, mode: rdi.GenerationMode, is_people: bool, rng: random.Random
) -> None:
    """Validate sheets assembly for PEOPLE and HH_IND modes with minimal stubs."""
    mocker.patch.object(rdi, "get_form", side_effect=[object(), object()])
    spy_uc = mocker.patch.object(rdi, "update_collectors")

    def gen_data(fn):
        match fn.__name__:
            case "generate_people_data":
                return lambda *_a, **_k: [{"index_id": 1}]
            case "generate_households_data":
                return lambda *_a, **_k: [{"household_id": 1, "individuals_start": 1, "individuals_count": 1}]
            case "generate_individuals_data":
                return lambda hh, *_a, **_k: [{"individual_id": 1, "household_id": hh[0]["household_id"]}]

    cfg = rdi.GeneratorConfig(mode=mode, office_slug="afghanistan", hh_amount=1, inds_per_hh=(1, 1), people=1)
    sheets = mode.get_sheets(cfg, gen_data, rng)

    if is_people:
        assert sheets == [(rdi.PEOPLE_SPEC, [{"index_id": 1}])]
        rdi.get_form.assert_called_once_with(rdi.PEOPLE_CHECKER_NAME, "afghanistan")
        spy_uc.assert_not_called()
    else:
        assert sheets[0][0] is rdi.HOUSEHOLDS_SPEC
        assert sheets[1][0] is rdi.INDIVIDUALS_SPEC
        assert sheets[0][1]
        assert sheets[1][1]
        spy_uc.assert_called_once()


def test_generation_mode_get_sheets_unknown_raises(rng: random.Random) -> None:
    cfg = rdi.GeneratorConfig(office_slug="afghanistan")

    class Unknown: ...

    with pytest.raises(ValueError, match="Unknown generation mode"):
        rdi.GenerationMode.get_sheets(Unknown(), cfg, gen_data=lambda *_: None, rng=rng)
