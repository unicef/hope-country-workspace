from typing import Any, Final, Mapping, NotRequired

from django.db.transaction import atomic

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.contrib.aurora.exceptions import TooManyBeneficiaryError
from country_workspace.models import AsyncJob, Batch, Household, Individual
from country_workspace.utils.config import BatchNameConfig, FailIfAlienConfig
from country_workspace.utils.fields import clean_field_names
from country_workspace.validators.beneficiaries import validate_beneficiaries


class Config(BatchNameConfig, FailIfAlienConfig):
    registration_reference_pk: str | None
    master_detail: bool
    household_column_prefix: NotRequired[str]
    individuals_column_prefix: str
    household_label_column: NotRequired[str]


RELATIONSHIP_HEAD: Final[str] = "HEAD"
RELATIONSHIP_FIELDNAME: Final[str] = "relationship"

ROLE_PRIMARY = "PRIMARY"
ROLE_ALTERNATE = "ALTERNATE"


def import_from_aurora(job: AsyncJob) -> dict[str, int]:
    """Import data from the Aurora system into the database within an atomic transaction.

    Args:
        job (AsyncJob): The job instance containing the configuration and context for data import.
            Expected keys in `job.config` correspond to the `Config` TypedDict.

    Returns:
        dict[str, int]: Counts of imported records:
            - "households": Number of households imported (0 if `master_detail` is False or None).
            - "individuals": Total number of individuals imported.

    Raises:
        ValueError: If record ID is invalid or missing.

    """
    with atomic():
        total = {"households": 0, "individuals": 0}
        records_data = []
        cfg: Config = job.config

        batch = Batch.objects.create(
            name=cfg["batch_name"],
            program=job.program,
            country_office=job.program.country_office,
            imported_by=job.owner,
            source=Batch.BatchSource.AURORA,
        )

        client = AuroraClient()
        for record in client.get(f"registration/{cfg['registration_reference_pk']}/records/"):
            try:
                record_id = int(record["flatten"]["id"])
            except (ValueError, TypeError, KeyError):
                raise ValueError(f"Invalid or missing record ID: {record.get('flatten', {}).get('id')}")

            individuals = create_individuals(batch, record["flatten"], cfg)
            total["individuals"] += len(individuals)
            if cfg["master_detail"] and individuals and individuals[0].household_id:
                total["households"] += 1
            records_data.append((record_id, individuals))

        validate_records(records_data, cfg)

    return total


def validate_records(records_data: list[tuple[int, list[Individual]]], cfg: Config) -> None:
    """Validate beneficiaries based on configuration and record data.

    Args:
        records_data: List of tuples containing record ID and created individuals.
        cfg: Configuration for validation and mapping.

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


def create_household(batch: Batch, data: dict[str, Any], prefix: str) -> Household:
    """Create a Household object from the provided data and associate it with a batch.

    Args:
        batch (Batch): The batch to which the household will be linked.
        data (dict[str, Any]): A dictionary containing household-related information.
        prefix (str): The prefix used to filter and group household-related information.

    Returns:
        Household: The newly created household instance.

    Raises:
        TooManyHouseholdsError: If multiple household entries are found in the provided data.

    """
    hh_data = _collect_by_prefix(data, prefix)
    count = len(hh_data)
    if count > 1:
        raise TooManyBeneficiaryError("Household", record_id=data["id"], count=count)
    flex_fields = clean_field_names(next(iter(hh_data.values()), {}))
    return batch.program.households.create(batch=batch, flex_fields=flex_fields)


def create_individuals(
    batch: Batch,
    data: dict[str, Any],
    cfg: Config,
) -> list[Individual]:
    """Create and associate Individual objects with an optional Household.

    Args:
        batch (Batch): The batch to which individuals will be linked.
        data (dict[str, Any]): A dictionary containing related information.
        cfg (Config): Configuration dictionary containing various settings for the import process.

    Returns:
        list[Individual]: A list of successfully created Individual instances.

    """
    household, individuals = None, []
    head_found = False

    inds_data = _collect_by_prefix(data, cfg.get("individuals_column_prefix"))

    if inds_data and cfg["master_detail"] and (hh_prefix := cfg.get("household_column_prefix")):
        household = create_household(batch, data, hh_prefix)

    for ind_data in inds_data.values():
        flex_fields = clean_field_names(ind_data)
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

    Args:
        household (Household): The household instance to update.
        ind_data (dict[str, Any]): A dictionary containing the individual's data,
            including relationship status and potential household name.
        household_label_column (str): The key in the individual's data that stores
            the name to assign to the household.

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
