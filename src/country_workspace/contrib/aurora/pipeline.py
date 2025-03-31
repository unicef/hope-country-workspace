from typing import Any, Mapping, Final, NotRequired

from django.db.transaction import atomic

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.models import AsyncJob, Batch, Household, Individual
from country_workspace.utils.config import BatchNameConfig, FailIfAlienConfig
from country_workspace.utils.fields import clean_field_names, uppercase_field_value


class Config(BatchNameConfig, FailIfAlienConfig):
    registration_reference_pk: str | None
    master_detail: bool
    household_column_prefix: NotRequired[str]
    individuals_column_prefix: str
    household_label_column: NotRequired[str]


RELATIONSHIP_HEAD: Final[str] = "HEAD"
RELATIONSHIP_FIELDNAME: Final[str] = "relationship"


def import_from_aurora(job: AsyncJob) -> dict[str, int]:
    """Import data from the Aurora system into the database within an atomic transaction.

    Args:
        job (AsyncJob): The job instance containing the configuration and context for data import.
            Expected keys in `job.config` correspond to the `Config` TypedDict.

    Returns:
        dict[str, int]: Counts of imported records:
            - "households": Number of households imported (0 if `master_detail` is False or None).
            - "individuals": Total number of individuals imported.

    """
    with atomic():
        total = {"households": 0, "individuals": 0}
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
            individuals = create_individuals(batch, record["flatten"], cfg)
            total["individuals"] += len(individuals)
            if cfg["master_detail"] and individuals and individuals[0].household_id:
                total["households"] += 1

    return total


def create_household(batch: Batch, data: dict[str, Any], prefix: str) -> Household:
    """Create a Household object from the provided data and associate it with a batch.

    Args:
        batch (Batch): The batch to which the household will be linked.
        data (dict[str, Any]): A dictionary containing household-related information.
        prefix (str): The prefix used to filter and group household-related information.

    Returns:
        Household: The newly created household instance.

    Raises:
        ValueError: If multiple household entries are found in the provided data.

    """
    flex_fields = _collect_by_prefix(data, prefix)
    if len(flex_fields) > 1:
        raise ValueError("Multiple households found")
    flex_fields = next(iter(flex_fields.values()), {})
    return batch.program.households.create(batch=batch, flex_fields=clean_field_names(flex_fields))
    # return batch.program.households.create(batch=batch, flex_fields=flex_fields)


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

    # for raw_individual in data.values():
        # individual = clean_field_names(raw_individual)
        # if not head_found:
    inds_data = _collect_by_prefix(data, cfg.get("individuals_column_prefix"))

    if inds_data and cfg["master_detail"] and (hh_prefix := cfg.get("household_column_prefix")):
        household = create_household(batch, data, hh_prefix)

    for individual in inds_data.values():
        household_label_column = cfg.get("household_label_column")
        if household and household_label_column and not head_found:
            head_found = _update_household_label_from_individual(household, individual, household_label_column)
        individuals.append(
            Individual(
                batch=batch,
                household_id=household.pk if household else None,
                name=individual.get("given_name", ""),
                flex_fields=individual,
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
            index, field = stripped.split("_", 1)
            result.setdefault(index, {})[field] = uppercase_field_value(field, v)
    # for key, value in data.items():
    #     if not key.startswith(prefix):
    #         continue
    #     index, field = key.removeprefix(prefix).split("_", 1)
    #     clean_field = clean_field_name(field)
    #     result.setdefault(index, {})[clean_field] = uppercase_field_value(clean_field, value)
    # return result


def _update_household_label_from_individual(
    household: Household, individual: Mapping[str, Any], household_label_column: str
) -> bool:
    """Update the household's name based on an individual's role and specified name field.

    Args:
        household (Household): The household instance to update.
        individual (dict[str, Any]): A dictionary containing the individual's data,
            including relationship status and potential household name.
        household_label_column (str): The key in the individual's data that stores
            the name to assign to the household.

    Returns:
        bool: True if the household name was updated (individual is head and name provided), False otherwise.

    """
    is_head = any(individual.get(k) == RELATIONSHIP_HEAD for k in individual if k.startswith(RELATIONSHIP_FIELDNAME))
    name = individual.get(household_label_column)
    if is_head and name:
        household.name = name
        household.save(update_fields=["name"])
        return True
    return False
