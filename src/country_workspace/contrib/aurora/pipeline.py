from dataclasses import dataclass, field
from typing import Any, Mapping, NotRequired
from contextlib import suppress

from django.db.transaction import atomic

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.contrib.aurora.exceptions import TooManyBeneficiaryError
from country_workspace.models.household import RELATIONSHIP_HEAD, RELATIONSHIP_FIELDNAME
from country_workspace.models import AsyncJob, Batch, Household, Individual, MappingProfile
from country_workspace.utils.config import BatchNameConfig, FailIfAlienConfig
from country_workspace.utils.fields import clean_field_names
from country_workspace.validators.beneficiaries import validate_beneficiaries


class Config(BatchNameConfig, FailIfAlienConfig):
    registration_reference_pk: str | None
    master_detail: bool
    household_column_prefix: NotRequired[str]
    individuals_column_prefix: str
    household_label_column: NotRequired[str]
    mapping_profile_pk: NotRequired[int]

@dataclass
class AuroraImporter:
    """Aurora data importer with mapping profile support."""

    job: AsyncJob
    cfg: Config
    client: AuroraClient = field(default_factory=AuroraClient)
    mapping_profile: MappingProfile | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.batch = Batch.objects.create(
            name=self.cfg["batch_name"],
            program=self.job.program,
            country_office=self.job.program.country_office,
            imported_by=self.job.owner,
            source=Batch.BatchSource.AURORA,
        )
        if self.cfg.get("mapping_profile_pk"):
            with suppress(MappingProfile.DoesNotExist):
                self.mapping_profile = MappingProfile.objects.get(id=self.cfg["mapping_profile_pk"], is_active=True)

    def run_import(self) -> dict[str, int]:
        """Execute the Aurora import process.

        Returns:
            dict[str, int]: Counts of imported records:
                - "households": Number of households imported.
                - "individuals": Number of individuals imported.

        """
        total = {"households": 0, "individuals": 0}
        records_data = []

        for record in self.client.get(f"registration/{self.cfg['registration_reference_pk']}/records/"):
            record_id = _extract_record_id(record)
            individuals = create_individuals(self.batch, record["flatten"], self.cfg, self.mapping_profile)
            total["individuals"] += len(individuals)
            if self.cfg["master_detail"] and individuals and individuals[0].household_id:
                total["households"] += 1
            records_data.append((record_id, individuals))

        validate_records(records_data, self.cfg)
        return total


def import_from_aurora(job: AsyncJob) -> dict[str, int]:
    """Import data from the Aurora system into the database within an atomic transaction."""
    with atomic():
        cfg: Config = job.config
        importer = AuroraImporter(job=job, cfg=cfg)
        return importer.run_import()


def validate_records(records_data: list[tuple[int, list[Individual]]], cfg: Config) -> None:
    """Validate beneficiaries based on configuration and record data.

    Raises:
        TooManyBeneficiaryError: If more than one Individual is created when master_detail is False.

    """
    mapping = {}
    for record_id, individuals in records_data:
        if cfg["master_detail"]:
            if individuals and individuals[0].household_id:
                mapping[record_id] = individuals[0].household
        else:
            if len(individuals) > 1:
                raise TooManyBeneficiaryError("Individual", record_id=record_id, count=len(individuals))
            if individuals:
                mapping[record_id] = individuals[0]

    if mapping:
        validate_beneficiaries(cfg, mapping)


def create_household(
    batch: Batch, data: dict[str, Any], prefix: str, mapping_profile: MappingProfile | None = None
) -> Household:
    """Create a Household object from the provided data and associate it with a batch.

    Returns:
        Household: The newly created household instance.

    Raises:
        TooManyHouseholdsError: If multiple household entries are found in the provided data.

    """
    hh_data = _collect_by_prefix(data, prefix)
    count = len(hh_data)
    if count > 1:
        raise TooManyBeneficiaryError("Household", record_id=data["id"], count=count)

    raw_fields = clean_field_names(next(iter(hh_data.values()), {}))
    flex_fields = mapping_profile.apply_all_rules(raw_fields) if mapping_profile else raw_fields

    return batch.program.households.create(batch=batch, flex_fields=flex_fields)


def create_individuals(
    batch: Batch,
    data: dict[str, Any],
    cfg: Config,
    mapping_profile: MappingProfile | None = None,
) -> list[Individual]:
    """Create and associate Individual objects with an optional Household.

    Returns:
        list[Individual]: A list of successfully created Individual instances.

    """
    household, individuals = None, []
    head_found = False

    inds_data = _collect_by_prefix(data, cfg.get("individuals_column_prefix"))

    if inds_data and cfg["master_detail"] and (hh_prefix := cfg.get("household_column_prefix")):
        household = create_household(batch, data, hh_prefix, mapping_profile)

    for ind_data in inds_data.values():
        cleaned_data = clean_field_names(ind_data)
        flex_fields = mapping_profile.apply_all_rules(cleaned_data) if mapping_profile else cleaned_data
        if household and (hh_label := cfg.get("household_label_column")) and not head_found:
            head_found = _update_household_label_from_individual(household, flex_fields, hh_label)
        individuals.append(
            Individual(
                batch=batch,
                household_id=household.pk if household else None,
                name=flex_fields.get("given_name", ""),
                flex_fields=flex_fields,
            )
        )
    return batch.program.individuals.bulk_create(individuals, batch_size=1000)


def _extract_record_id(record: dict[str, Any]) -> int:
    """Extract and validate record ID from Aurora record.

    Raises:
        ValueError: If record ID is invalid or missing.

    """
    try:
        return int(record["flatten"]["id"])
    except (ValueError, TypeError, KeyError):
        raise ValueError(f"Invalid or missing record ID: {record.get('flatten', {}).get('id')}")


def _collect_by_prefix(data: dict[str, Any], prefix: str) -> dict[str, dict[str, Any]]:
    """Extract and group fields from a dictionary based on a given prefix.

    Args:
        data (dict[str, Any]): The input data containing multiple prefixed keys.
        prefix (str): The prefix used to filter and group keys.

    Returns:
        dict[str, dict[str, Any]]: A dictionary where each key is an index extracted from the original keys,
            and each value is a dictionary of the corresponding grouped fields with normalized field names
            and, for specific fields, values converted to uppercase. Returns an empty dictionary if no
            matching keys are found.

    Raises:
        ValueError: If a key with the specified prefix does not contain an underscore after the prefix.

    Examples:
        >>> data = {"user_0_relationship": "head", "user_0_gender": "male", "user_1_gender": "female"}
        >>> _collect_by_prefix(data, "user_")
        {'0': {'relationship': 'HEAD', 'gender': 'MALE'}, '1': {'gender': 'FEMALE'}}
        >>> _collect_by_prefix(data, "other_")
        {}

    """
    result = {}
    for k, v in data.items():
        if (stripped := k.removeprefix(prefix)) != k:
            try:
                index, field = stripped.split("_", 1)
                result.setdefault(index, {})[field] = v
            except ValueError:
                raise ValueError(f"Field name '{k}' after removing prefix '{prefix}' must contain an underscore.")
    return result


def _update_household_label_from_individual(
    household: Household, ind_data: Mapping[str, Any], household_label_column: str
) -> bool:
    """Update the household's name based on an individual's role and specified name field.

    Returns:
        bool: True if the household name was updated (individual is head and name provided), False otherwise.

    """
    is_head = any(ind_data.get(k) == RELATIONSHIP_HEAD for k in ind_data if k == RELATIONSHIP_FIELDNAME)
    name = ind_data.get(household_label_column)
    if is_head and name:
        household.name = name
        household.save(update_fields=["name"])
        return True
    return False
