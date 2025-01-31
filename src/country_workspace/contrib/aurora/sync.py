from typing import Any
from django.db.transaction import atomic

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.models import AsyncJob, Batch, Household, Individual
from country_workspace.utils.fields import clean_field_name


def sync_aurora_job(job: AsyncJob) -> dict[str, int]:
    """Synchronize data from the Aurora system into the database for the given job within an atomic transaction.

    Args:
        job (AsyncJob): The job instance containing configuration and context for synchronization.

    Returns:
        dict[str, int]: A dictionary with counts of households and individuals created.

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
    Create a Household object from the given data.

    Args:
        batch (Batch): The batch associated with the household.
        data (dict[str, Any]): The input data containing household details.

    Returns:
        Household: The created household instance.

    Raises:
        ValueError: If multiple households are found in the data.

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
    """Create Individual objects associated with a given Household.

    Args:
        household (Household): The household to which individuals belong.
        data (dict[str, Any]): The input data containing individual details.
        household_name_column (str): The column used to identify the household head.

    Returns:
        list[Individual]: A list of created Individual instances.

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

    """
    to_uppercase = ("relationship", "gender", "disability", "role")
    result = {}
    for k, v in data.items():
        if (stripped := k.removeprefix(prefix)) != k:
            index, field = stripped.split("_", 1)
            field_clean = clean_field_name(field)
            result.setdefault(index, {})[field_clean] = (
                v.upper() if isinstance(v, str) and field_clean in to_uppercase else v
            )
    if not result:
        raise ValueError(f"No data found with prefix '{prefix}'")
    return result


def _update_household_name_from_individual(
    household: Household,
    individual: dict[str, Any],
    household_name_column: str,
) -> bool:
    """Update the household name based on an individual's relationship and name field.

    This method checks if the individual is marked as the head of the household
    and updates the household name accordingly.

    Args:
        household (Household): The household to update.
        individual (dict[str, Any]): The individual data containing potential household name information.
        household_name_column (str): The name of the column in household that contains the name of the individuals.

    Returns:
        None

    """
    if any(individual.get(k) == "HEAD" for k in individual if k.startswith("relationship")):
        for k, v in individual.items():
            if clean_field_name(k) == household_name_column:
                household.name = v
                household.save()
                return True
    raise ValueError("No head found")
