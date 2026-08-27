import logging
from base64 import b64encode
from collections import defaultdict
from collections.abc import Generator
from typing import Any, cast, Mapping, NamedTuple

from PIL import Image
from django.db.transaction import atomic
from hope_smart_import.readers import open_xls_multi, SheetNotError
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as RDIImage

from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.context import batch_ctx
from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch
from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT
from country_workspace.models import AsyncJob, Batch, Household, Individual
from country_workspace.utils.fields import Record, to_reference_key
from country_workspace.utils.imports import get_xlsx_originating_id, normalize_file_name
from country_workspace.utils.functional import compose
from country_workspace.utils.import_flow import (
    build_import_processor,
    get_or_create_collector,
    run_batch_postprocessing,
)
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs
from country_workspace.notifications.signals import data_imported_signal

from .config import Config, SheetName, Sheet
from .exceptions import ColumnConfigurationError, SheetProcessingError, SheetNotFoundError
from .utils import date_to_iso_string, datetime_to_date

logger = logging.getLogger(__name__)

# household_id values meaning "no household": 0 marks an Individual without a Household (e.g. an external Collector)
NO_HOUSEHOLD_KEYS = (None, "", 0, "0")


class BeneficiaryImportResult(NamedTuple):
    """Individuals resulting from a beneficiary sheet.

    ``reference_pks`` maps the ``individual_id`` used *in the sheet being imported*
    to the pk of the resulting record. It cannot be derived from ``mapping``: a
    reused external collector keeps the ``individual_id`` of the import that first
    created it, which is unrelated to the ids of the sheet referencing it now.
    """

    mapping: dict[Any, Individual]
    reference_pks: dict[str, int]


def image_location(image: RDIImage) -> tuple[int, int]:
    return image.anchor._from.row, image.anchor._from.col


def image_content(rdi_image: RDIImage) -> tuple[str | None, str]:
    image = Image.open(rdi_image.ref)
    content_type = Image.MIME.get(image.format)
    rdi_image.ref.seek(0)
    content = b64encode(rdi_image.ref.read()).decode()
    return content_type, content


def extract_images(filepath: str, *sheet_names: str) -> Generator[Mapping[int, Mapping[int, str]], None, None]:
    workbook = load_workbook(filepath)
    for n in sheet_names:
        worksheet = workbook[n]
        images: dict[int, dict[int, str]] = defaultdict(dict)
        for rdi_image in worksheet._images:
            row, column = image_location(rdi_image)
            content_type, content = image_content(rdi_image)
            images[row - 1][column] = VALUE_FORMAT.format(mimetype=content_type, content=content)
        yield images


def merge_images(sheet: Sheet, sheet_images: Mapping[int, Mapping[int, str]], start_at_row: int = 0) -> Sheet:
    for i, row in enumerate(sheet, start=start_at_row):
        if i in sheet_images:
            yield {key: sheet_images[i].get(j, value) for j, (key, value) in enumerate(row.items())}
        else:
            yield row


def get_value(row: Record, column_name: str) -> Any:
    if column_name in row:
        return row[column_name]
    raise ColumnConfigurationError(column_name)


def normalize_row_structure(row: Record, people_prefix: str | None = None) -> tuple[Record, str | None]:
    if people_prefix:
        row = {k.removeprefix(people_prefix): v for k, v in row.items()}
    name_column = next((key for key in row if key.startswith("full") and "name" in key), None)
    return row, name_column


def filter_rows_with_household_pk(config: Config, sheet: Sheet) -> Sheet:
    household_id_column = config["household_id_column"]

    def has_household_pk(row: Record) -> bool:
        # only truly empty cells drop the row; household_id 0 means "no household" and must be kept
        return get_value(row, household_id_column) not in (None, "")

    return filter(has_household_pk, sheet)


def read_sheets(config: Config, filepath: str, *sheet_names: str) -> Generator[Sheet, None, None]:
    cell_mapper = compose(datetime_to_date, date_to_iso_string)
    try:
        first_line = config.get("first_line")
        start_at_row = first_line - 2 if first_line > 1 else 0

        sheets = open_xls_multi(
            filepath, indices_or_names=list(sheet_names), value_mapper=cell_mapper, start_at_row=start_at_row
        )
        sheet_images = extract_images(filepath, *sheet_names)
        for (_, sheet), images in zip(sheets, sheet_images, strict=False):
            sheet_with_images = merge_images(sheet, images, start_at_row)
            if config["master_detail"]:
                yield filter_rows_with_household_pk(config, sheet_with_images)
            else:
                yield sheet_with_images
    except (IndexError, SheetNotError) as e:
        raise SheetNotFoundError(sheet_names) from e


def process_households(sheet: Sheet, job: AsyncJob, batch: Batch, config: Config) -> Mapping[int, Household]:
    mapping = {}
    file_name = normalize_file_name(job.file.name)
    epoch_ms = int(batch.import_date.timestamp() * 1000)
    household_mapping_id = config.get("household_mapping_id")
    transform_row = build_import_processor(
        program=job.program,
        model=Household,
        mapping_id=household_mapping_id,
        source=Batch.BatchSource.RDI,
    )

    job.ensure_not_cancelled(refresh=True)
    for row in sheet:
        job.ensure_not_cancelled(refresh=True)
        if (household_key := get_value(row, config["household_id_column"])) in mapping:
            raise SheetProcessingError(SheetName.HOUSEHOLDS, household_key)
        originating_id = get_xlsx_originating_id(file_name, household_key, epoch=epoch_ms)
        try:
            mapping[household_key] = cast(
                "Household",
                Household.objects.create(
                    batch_id=batch.pk,
                    name=str(get_value(row, config["household_label"])),
                    originating_id=originating_id,
                    flex_fields=transform_row(row),
                    raw_data=row,
                ),
            )
        except Exception as e:
            raise SheetProcessingError(SheetName.HOUSEHOLDS, household_key) from e

    return mapping


def process_beneficiaries(
    sheet: Sheet, job: AsyncJob, batch: Batch, config: Config, household_mapping: Mapping[int, Household] | None = None
) -> BeneficiaryImportResult:
    file_name = normalize_file_name(job.file.name)
    epoch_ms = int(batch.import_date.timestamp() * 1000)
    mapping: dict[Any, Individual] = {}
    reference_pks: dict[str, int] = {}
    people_prefix = config.get("people_prefix") if household_mapping is None else None
    household_id_column = config.get("household_id_column") if household_mapping is not None else None
    sheet_name = SheetName.PEOPLE if household_mapping is None else SheetName.INDIVIDUALS
    individual_mapping_id = config.get("individual_mapping_id")
    transform_row = build_import_processor(
        program=job.program,
        model=Individual,
        mapping_id=individual_mapping_id,
        source=Batch.BatchSource.RDI,
    )

    job.ensure_not_cancelled(refresh=True)
    invalid_household_refs: list[tuple[Any, Any]] = []
    for row in sheet:
        job.ensure_not_cancelled(refresh=True)
        beneficiary_key = get_value(row, config["beneficiary_id_column"])
        if beneficiary_key in mapping:
            raise SheetProcessingError(sheet_name, beneficiary_key)
        originating_id = get_xlsx_originating_id(file_name, beneficiary_key, epoch=epoch_ms)
        cleaned_row, name_column = normalize_row_structure(row, people_prefix)
        name = cleaned_row.get(name_column) if name_column else ""
        household = None
        is_external_collector = False
        if household_mapping is not None and household_id_column:
            household_key = get_value(cleaned_row, household_id_column)
            if household_key in NO_HOUSEHOLD_KEYS:
                # household_id 0 marks an external Collector (issue #427)
                is_external_collector = True
            elif (household := household_mapping.get(household_key)) is None:
                invalid_household_refs.append((beneficiary_key, household_key))
                continue

        try:
            individual_fields = transform_row(cleaned_row)
            if is_external_collector:
                # External collectors are deduplicated program-wide: the first
                # occurrence is reused, linked to households only via role refs.
                individual, _created = get_or_create_collector(
                    program=batch.program,
                    batch=batch,
                    individual_fields=individual_fields,
                    raw_data=row,
                    originating_id=originating_id,
                    name=name,
                )
            else:
                individual = cast(
                    "Individual",
                    Individual.objects.create(
                        batch_id=batch.pk,
                        name=name,
                        household=household,
                        originating_id=originating_id,
                        flex_fields=individual_fields,
                        raw_data=row,
                    ),
                )
        except Exception as e:
            raise SheetProcessingError(sheet_name, beneficiary_key) from e

        mapping[beneficiary_key] = individual
        # index by this sheet's id, which a reused collector does not carry itself
        if reference := to_reference_key(individual_fields.get("individual_id")):
            reference_pks[reference] = individual.pk

    if invalid_household_refs:
        logger.error(
            "Skipped %d individual(s) with invalid household references in sheet %s: %s",
            len(invalid_household_refs),
            sheet_name,
            ", ".join(f"individual {ind!r} -> household {hh!r}" for ind, hh in invalid_household_refs),
        )

    return BeneficiaryImportResult(mapping, reference_pks)


def import_from_rdi(job: AsyncJob) -> dict[str, int]:
    job.ensure_not_cancelled(refresh=True)
    with atomic():
        config: Config = job.config
        batch = Batch.objects.create(
            name=config["batch_name"],
            program=job.program,
            country_office=job.program.country_office,
            imported_by=job.owner,
            source=Batch.BatchSource.RDI,
            status=Batch.BatchStatus.LOADING,
        )
        job.batch = batch
        job.save(update_fields=["batch"])

        with batch_ctx(batch.pk):
            job.ensure_not_cancelled(refresh=True)
            if config["master_detail"]:
                result = _import_master_detail(job, batch, config)
            else:
                result = _import_people_only(job, batch, config)

    run_batch_postprocessing(
        batch,
        household_transformer_id=config.get("household_transformer_id"),
        individual_transformer_id=config.get("individual_transformer_id"),
    )

    detect_and_mark_collisions_for_batch(batch)

    job.ensure_not_cancelled(refresh=True)
    if not config.get("validate_after_import"):
        batch.status = Batch.BatchStatus.COMPLETE
        batch.save(update_fields=["status"])
        data_imported_signal.send(
            sender=Batch,
            program_id=batch.program_id,
            batch_id=batch.id,
            record_count=sum(result.values()),
            source=Batch.BatchSource.RDI,
        )
        return result

    job.ensure_not_cancelled(refresh=True)
    if job.config.get("master_detail"):
        queryset = batch.household_set.filter(removed=False).prefetch_related("members")
    else:
        queryset = batch.individual_set.filter(household=None, removed=False)

    create_validation_jobs(
        description=f"Validate records for batch {batch.pk}",
        owner=job.owner,
        program=job.program,
        queryset=queryset,
        validation_scope="batch",
    )
    batch.status = Batch.BatchStatus.COMPLETE
    batch.save(update_fields=["status"])
    data_imported_signal.send(
        sender=Batch,
        program_id=batch.program_id,
        batch_id=batch.id,
        record_count=sum(result.values()),
        source=Batch.BatchSource.RDI,
    )
    return result


def _import_master_detail(job: AsyncJob, batch: Batch, config: Config) -> dict[str, int]:
    household_sheet, individual_sheet = read_sheets(config, job.file, SheetName.HOUSEHOLDS, SheetName.INDIVIDUALS)
    household_mapping = process_households(household_sheet, job, batch, config)
    beneficiaries = process_beneficiaries(individual_sheet, job, batch, config, household_mapping)
    _sync_ind_pks(household_mapping, beneficiaries.reference_pks)
    return {"household": len(household_mapping), "individual": len(beneficiaries.mapping)}


def _import_people_only(job: AsyncJob, batch: Batch, config: Config) -> dict[str, int]:
    (people_sheet,) = read_sheets(config, job.file, SheetName.PEOPLE)
    people = process_beneficiaries(people_sheet, job, batch, config)
    return {"people": len(people.mapping)}


def _sync_ind_pks(households_mapping: Mapping[Any, Household], reference_pks: Mapping[str, int]) -> None:
    """Replace the sheet-local individual references on households with real pks.

    References that cannot be resolved are cleared rather than left alone: a
    sheet-local id kept in place would later be read as a pk and silently point at
    an unrelated record.
    """
    fields = HOUSEHOLD_ROLE_REF_FIELDS
    unresolved: list[str] = []

    def resolve(household: Household, field: str, value: Any) -> int | None:
        reference = to_reference_key(value)
        pk = reference_pks.get(reference) if reference else None
        if reference and pk is None:
            unresolved.append(f"household {household.pk!r} {field}={value!r}")
        return pk

    for household in households_mapping.values():
        flex_fields = household.flex_fields.copy()
        flex_fields[fields.head_of_household] = resolve(
            household, fields.head_of_household, flex_fields.get(fields.head_of_household)
        )
        flex_fields[fields.primary_collector] = resolve(
            household, fields.primary_collector, flex_fields.get(fields.primary_collector)
        )

        if alt_id := flex_fields.get(fields.alternate_collector):
            flex_fields[fields.alternate_collector] = resolve(household, fields.alternate_collector, alt_id)

        household.flex_fields = flex_fields
        household.save(update_fields=["flex_fields"])

    if unresolved:
        logger.warning("Cleared %d unresolved household role reference(s): %s", len(unresolved), ", ".join(unresolved))
