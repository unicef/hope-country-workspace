from typing import Any

from django.db.transaction import atomic

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.models import AsyncJob, Batch, Household, Individual
from country_workspace.utils.config import BatchNameConfig, FailIfAlienConfig
from country_workspace.utils.fields import uppercase_field_value, RecordPreprocessor, create_json_record_preprocessor


class Config(BatchNameConfig, FailIfAlienConfig):
    registration_reference_pk: str | None
    household_column_prefix: str
    individuals_column_prefix: str
    household_label_column: str


def import_from_aurora(job: AsyncJob) -> dict[str, int]:
    """Import data from the Aurora system into the database within an atomic transaction.

    Args:
        job (AsyncJob): The job instance containing the configuration and context for data import.
            Expected keys in `job.config`:
            - "batch_name" (str): The name for the newly created batch.
            - "registration_reference_pk" (int): The unique identifier of the registration to import.
            - "household_column_prefix" (str, optional): The prefix for household-related columns.
            - "individuals_column_prefix" (str, optional): The prefix for individual-related columns.
            - "household_label_column" (str, optional): The column name used to determine the household label.

    Returns:
        dict[str, int]: A dictionary with the counts of successfully created records:
            - "households": The number of households imported.
            - "individuals": The total number of individuals imported.

    """
    config: Config = job.config
    total_hh = total_ind = 0
    batch = Batch.objects.create(
        name=config["batch_name"],
        program=job.program,
        country_office=job.program.country_office,
        imported_by=job.owner,
        source=Batch.BatchSource.AURORA,
    )
    client = AuroraClient()
    individual_preprocessor = create_json_record_preprocessor(config, job.program.individual_checker)
    household_preprocessor = create_json_record_preprocessor(config, job.program.household_checker)
    with atomic():
        for record in client.get(f"registration/{config['registration_reference_pk']}/records/"):
            inds_data = _collect_by_prefix(record["flatten"], config.get("individuals_column_prefix"))
            if inds_data:
                hh = create_household(
                    batch, record["flatten"], config.get("household_column_prefix"), household_preprocessor
                )
                total_hh += 1
                total_ind += len(
                    create_individuals(
                        household=hh,
                        data=inds_data,
                        household_label_column=config.get("household_label_column"),
                        preprocess_record=individual_preprocessor,
                    )
                )
    return {"households": total_hh, "individuals": total_ind}


def create_household(
    batch: Batch, data: dict[str, Any], prefix: str, preprocess_record: RecordPreprocessor
) -> Household:
    """
    Create a Household object from the provided data and associate it with a batch.

    Args:
        batch (Batch): The batch to which the household will be linked.
        data (dict[str, Any]): A dictionary containing household-related information.
        prefix (str): The prefix used to filter and group household-related information.
        preprocess_record (RecordPreprocessor): The function normalizing field names and checking if they are valid.

    Returns:
        Household: The newly created household instance.

    Raises:
        ValueError: If multiple household entries are found in the provided data.

    """
    flex_fields = _collect_by_prefix(data, prefix)
    if len(flex_fields) > 1:
        raise ValueError("Multiple households found")
    return batch.program.households.create(batch=batch, flex_fields=preprocess_record(flex_fields))


def create_individuals(
    household: Household, data: dict[str, Any], household_label_column: str, preprocess_record: RecordPreprocessor
) -> list[Individual]:
    """Create and associate Individual objects with a given Household.

    Args:
        household (Household): The household to which the individuals will be linked.
        data (dict[str, Any]): A dictionary mapping indices to individual details.
        household_label_column (str): The key in the individual data used to determine the household label.
        preprocess_record (RecordPreprocessor): The function normalizing field names and checking if they are valid.

    Returns:
        list[Individual]: A list of successfully created Individual instances.

    """
    individuals = []
    head_found = False

    for individual in data.values():
        if not head_found:
            head_found = _update_household_label_from_individual(household, individual, household_label_column)
        individuals.append(
            Individual(
                batch=household.batch,
                household_id=household.pk,
                name=individual.get("given_name", ""),
                flex_fields=preprocess_record(individual),
            ),
        )
    return household.program.individuals.bulk_create(individuals)


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
    return result


def _update_household_label_from_individual(
    household: Household, individual: dict[str, Any], household_label_column: str
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
    is_head = any(individual.get(k) == "HEAD" for k in individual if k.startswith("relationship"))
    name = individual.get(household_label_column)
    if is_head and name:
        household.name = name
        household.save(update_fields=["name"])
        return True
    return False
