from typing import Any
from itertools import batched
from dataclasses import dataclass, field

from django.db.models import QuerySet
from django.db import transaction, DatabaseError


from country_workspace.contrib.hope.client import HopeClient
from country_workspace.models import AsyncJob
from country_workspace.workspaces.models import CountryHousehold

from requests.exceptions import RequestException
from json import JSONDecodeError
from country_workspace.exceptions import RemoteError
from country_workspace.contrib.hope.constants import HOUSEHOLD_PUSH_BATCH_SIZE


@dataclass
class PushProcessor:
    """Handles pushing household data to an external system through the HopeClient API."""

    queryset: QuerySet[CountryHousehold]
    co_slug: str
    batch_name: str
    program_id: str
    client: HopeClient = field(default_factory=HopeClient)
    total: dict[str, Any] = field(default_factory=lambda: {"households": 0, "errors": []})
    rdi_id: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Initialize the base path for API requests."""
        self.base_path = f"{self.co_slug}/rdi/"

    def validate_households(self) -> None:
        """Validate each household and its members in the queryset.

        Adds errors to `self.total["errors"]` if any household or member is invalid.
        """
        for hh in self.queryset.iterator():
            if not hh.is_valid():
                self.total["errors"].append(f"HH #{hh.pk} invalid or unvalidated.")
            for ind in hh.members.all():
                if not ind.is_valid():
                    self.total["errors"].append(f"Individual #{ind.pk} invalid or unvalidated.")

    def rdi_create(self) -> None:
        """Create a new RDI record in the external system.

        Sets `self.rdi_id` if the creation is successful.
        """
        path = f"{self.base_path}create/"
        data = {"name": self.batch_name, "program": self.program_id}
        if response := self.safe_post(path, data, "Error creating RDI"):
            self.rdi_id = response.get("id")

    def rdi_push_lax(self) -> None:
        """
        Pushes household data in batches to the external RDI system.

        Adds errors to `self.total["errors"]`, if `rdi_id` is not set.
        Successfully pushed records are marked as removed.
        """
        if self.rdi_id is None:
            self.total["errors"].append("Cannot push data: rdi_id is not set")
            return
        path = f"{self.base_path}{self.rdi_id}/push/lax/"
        for batch in batched(self.queryset.iterator(), HOUSEHOLD_PUSH_BATCH_SIZE):
            batch_ids, batch_data = PushProcessor.prepare_batch(batch)
            response = self.safe_post(path, batch_data, "Error pushing data")
            successful_ids = self.process_batch_response(response, batch_ids)
            if successful_ids and not self.total["errors"]:
                self.mark_batch_removed(successful_ids)

    def rdi_complete(self) -> None:
        """Mark the RDI process as completed in the external system.

        Adds errors to `self.total["errors"]`, if `rdi_id` is not set.
        """
        if self.rdi_id is None:
            self.total["errors"].append("Cannot complete RDI: rdi_id is not set")
            return
        path = f"{self.base_path}{self.rdi_id}/completed/"
        self.safe_post(path, None, "Error completing RDI")

    def safe_post(self, path: str, data: Any, error_msg: str) -> dict[str, Any] | None:
        """
        Send a POST request to the HopeClient API and handles errors.

        Args:
            path (str): API endpoint path.
            data (Any): Payload to send in the request.
            error_msg (str): Error message prefix for logging.

        Returns:
            dict[str, Any] | None: API response or None if an error occurs.

        """
        try:
            return self.client.post(path, data)
        except (RequestException, JSONDecodeError, RemoteError) as e:
            self.total["errors"].append(f"{error_msg}: {e}")
            return None

    @staticmethod
    def prepare_batch(batch: list) -> tuple[list[int], list[dict]]:
        """
        Prepare a batch of household data for API submission.

        Args:
            batch (list): List of household objects.

        Returns:
            tuple[list[int], list[dict]]: A tuple of household IDs and transformed data.

        """
        ids = [item.id for item in batch]
        data = [
            {**map_fields(item.flex_fields), "members": [map_fields(m.flex_fields) for m in item.members.all()]}
            for item in batch
        ]
        return ids, data

    def process_batch_response(self, response: dict | None, batch_ids: list[int]) -> list[int]:
        """
        Process the API response for a batch push operation.

        Args:
            response (dict | None): API response.
            batch_ids (list[int]): List of household IDs in the batch.

        Returns:
            list[int]: List of successfully processed IDs.

        """
        match response:
            case {"processed": int(p), "accepted": int(a)} if p == a == len(batch_ids):
                self.total["households"] = self.total.get("households", 0) + a
                return batch_ids
            case {"errors": int(e)} if e > 0:
                self.total["errors"].append(f"Error pushing data for IDs: {batch_ids} - {response}")
            case None:
                self.total["errors"].append(f"Batch failed for IDs: {batch_ids}")
            case _:
                self.total["errors"].append(f"Unexpected response for IDs: {batch_ids} - {response}")
        return []

    def mark_batch_removed(self, successful_ids: list[int]) -> None:
        """
        Mark successfully pushed households and members as removed in the database.

        Args:
            successful_ids (list[int]): List of successfully pushed household IDs.

        """
        try:
            with transaction.atomic():
                households = list(CountryHousehold.objects.filter(id__in=successful_ids))
                for hh in households:
                    for ind in hh.members.all():
                        ind.removed = True
                        ind.save()
                    hh.removed = True
                    hh.save()
        except (DatabaseError, Exception) as e:
            self.total["errors"].append(f"Failed to mark IDs {successful_ids} as removed: {e}")


def push_to_hope_core(job: AsyncJob) -> dict[str, Any]:
    """
    Execute the data push workflow for a given job, performing validation, creation, data pushing, and finalization.

    Args:
        job (AsyncJob): The job configuration containing relevant identifiers and parameters.

    Returns:
        dict[str, Any]: Summary of the operation including processed households and errors.

    """
    processor = PushProcessor(
        queryset=CountryHousehold.objects.filter(pk__in=job.config["pks"]),
        co_slug=job.program.country_office.slug,
        batch_name=job.config.get("batch_name"),
        program_id=job.program.hope_id,
    )
    steps = (
        processor.validate_households,
        processor.rdi_create,
        processor.rdi_push_lax,
        processor.rdi_complete,
    )
    for step in steps:
        step()
        if processor.total["errors"]:
            break
    return processor.total


def map_fields(fields: dict[str, str]) -> dict[str, str]:
    """
    Map keys in a dictionary to alternative names based on a predefined mapping.

    Args:
        fields (dict[str, str]): A dictionary containing field names as keys and their values.

    Returns:
        dict[str, str]: A new dictionary with keys mapped according to the predefined mapping.

    """
    to_map = {
        "gender": "sex",
    }
    return {to_map.get(k, k): v for k, v in fields.items()}
