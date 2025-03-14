from typing import Any

from django.db.transaction import atomic

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.models import AsyncJob, Batch, Household, Individual
from country_workspace.utils.fields import clean_field_name, uppercase_field_value


def import_from_aurora(job: AsyncJob) -> dict[str, int]:
    """Import data from the Aurora system into the database within an atomic transaction.

    Args:
        job (AsyncJob): The job instance containing the configuration and context for data synchronization.
            Expected keys in `job.config`:
            - "batch_name" (str): The name for the newly created batch.
            - "registration_reference_pk" (int): The unique identifier of the registration to import.
            - "household_name_column" (str, optional): The column name used to determine the household head.

    Returns:
        dict[str, int]: A dictionary with the counts of successfully created records:
            - "households": The number of households imported.
            - "individuals": The total number of individuals imported.

    """
    total_hh = total_ind = 0
    batch_name = job.config["batch_name"]
    batch = Batch.objects.create(
        name=batch_name,
        program=job.program,
        country_office=job.program.country_office,
        imported_by=job.owner,
        source=Batch.BatchSource.AURORA,
    )

    registration = job.config["registration_reference_pk"]
    client = AuroraClient()
    with atomic():
        for record in client.get(f"registration/{registration}/records/"):
            hh = create_household(batch, record["flatten"])
            total_hh += 1
            total_ind += len(
                create_individuals(
                    household=hh,
                    data=record["flatten"],
                    household_name_column=job.config.get("household_name_column"),
                )
            )

    return {"households": total_hh, "individuals": total_ind}


def create_household(batch: Batch, data: dict[str, Any]) -> Household:
    """
    Create a Household object from the provided data and associate it with a batch.

    Args:
        batch (Batch): The batch to which the household will be linked.
        data (dict[str, Any]): A dictionary containing household-related information,
            typically prefixed with "household_".

    Returns:
        Household: The newly created household instance.

    Raises:
        ValueError: If multiple household entries are found in the provided data.

    """
    flex_fields = _collect_by_prefix(data, prefix="household_")

    if len(flex_fields) == 1:
        flex_fields = next(iter(flex_fields.values()))
    else:
        raise ValueError("Multiple households found")

    return batch.program.households.create(batch=batch, flex_fields=flex_fields)


def create_individuals(
    household: Household,
    data: dict[str, Any],
    household_name_column: str,
) -> list[Individual]:
    """Create and associate Individual objects with a given Household.

    Args:
        household (Household): The household to which the individuals will be linked.
        data (dict[str, Any]): A dictionary containing individual details, typically
            structured with a prefix for multiple individuals.
        household_name_column (str): The key in the individual data used to determine
            the household head's name.

    Returns:
        list[Individual]: A list of successfully created Individual instances.

    Raises:
        ValueError: If no household head is identified in the provided data.

    """
    individuals = []
    head_found = False

    individuals_data = _collect_by_prefix(data, prefix="individuals_")
    for individual in individuals_data.values():
        if not head_found:
            head_found = _update_household_name_from_individual(household, individual, household_name_column)
        fullname_field = next((k for k in individual if k.startswith("given_name")), None)
        individuals.append(
            Individual(
                batch=household.batch,
                household_id=household.pk,
                name=individual.get(fullname_field, ""),
                flex_fields=individual,
            ),
        )
    if not head_found:
        raise ValueError(f"No head of household {household.flex_fields} found")
    return household.program.individuals.bulk_create(individuals)


def _collect_by_prefix(data: dict[str, Any], prefix: str) -> dict[str, dict[str, Any]]:
    """Extract and group fields from a dictionary based on a given prefix.

    Args:
        data (dict[str, Any]): The input data containing multiple prefixed keys.
        prefix (str): The prefix used to filter and group keys.

    Returns:
        dict[str, dict[str, Any]]: A dictionary where each key is an index extracted from the original keys,
        and each value is a dictionary of the corresponding grouped fields (with normalized field names and,
        for specific fields, values converted to uppercase).

    Raises:
        ValueError: If no matching data is found with the specified prefix.

    Examples:
        >>> data = {
        ...     "user_0_relationship_h_c": "head",
        ...     "user_0_gender_i_c": "male",
        ...     "user_0_other_key": "other",
        ...     "user_1_relationship_h_c": "son_daughter",
        ...     "user_1_gender_i_c": "female",
        ...     "user_1_other_key": "moreover",
        ... }
        >>> _collect_by_prefix(data, "user_")
        {'0': {'relationship': 'HEAD', 'gender': 'MALE', 'other_key': 'other'},
         '1': {'relationship': 'SON_DAUGHTER', 'gender': 'FEMALE', 'other_key': 'moreover'}}
        >>> _collect_by_prefix(data, "nonexistent_")
        Traceback (most recent call last):
        ...
        ValueError: No data found with prefix 'nonexistent_'

    """
    result = {}
    for k, v in data.items():
        if (stripped := k.removeprefix(prefix)) != k:
            index, field = stripped.split("_", 1)
            field_clean = clean_field_name(field)
            result.setdefault(index, {})[field_clean] = uppercase_field_value(field_clean, v)
    if not result:
        raise ValueError(f"No data found with prefix '{prefix}'")
    return result


def _update_household_name_from_individual(
    household: Household,
    individual: dict[str, Any],
    household_name_column: str,
) -> bool:
    """Update the household's name based on an individual's role and specified name field.

    Args:
        household (Household): The household instance to update.
        individual (dict[str, Any]): A dictionary containing the individual's data,
            including relationship status and potential household name.
        household_name_column (str): The key in the individual's data that stores
            the name to assign to the household.

    Returns:
        bool: True if the household name was updated, False otherwise.

    """
    if any(individual.get(k) == "HEAD" for k in individual if k.startswith("relationship")):
        name = individual.get(household_name_column)
        if name:
            household.name = name
            household.save()
            return True
    return False
