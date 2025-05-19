from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from itertools import batched
from json import JSONDecodeError
from typing import Any

from django.db import DatabaseError, transaction
from django.db.models import QuerySet
from requests.exceptions import RequestException

from country_workspace.contrib.hope.client import HopeClient
from country_workspace.contrib.hope.constants import HOUSEHOLD_PUSH_BATCH_SIZE
from country_workspace.exceptions import RemoteError
from country_workspace.models import AsyncJob
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual
from country_workspace.utils.fields import map_fields


@dataclass
class PushProcessor:
    """Handles pushing beneficiaries data to an external system through the HopeClient API."""

    co_slug: str
    batch_name: str
    program_id: str
    master_detail: bool
    queryset: QuerySet[CountryHousehold] = field(default_factory=lambda: CountryHousehold.objects.none())
    client: HopeClient = field(default_factory=HopeClient)
    total: dict[str, Any] = field(default_factory=lambda: {"errors": []})
    rdi_id: str | None = field(default=None, init=False)
    model: type = field(init=False)
    push_endpoint: str = field(init=False)
    has_members: bool = field(init=False)

    def __post_init__(self) -> None:
        self.base_path = f"{self.co_slug}/rdi/"
        self.model, self.push_endpoint, self.has_members = (
            (CountryHousehold, "push/lax/", True) if self.master_detail else (CountryIndividual, "push/people/", False)
        )

    def set_queryset(self, pks: list[int]) -> None:
        """Set the queryset based on master_detail and provided pks."""
        qs = self.model.objects.filter(pk__in=pks)
        self.queryset = qs.prefetch_related("members") if self.master_detail else qs

    def check_beneficiaries_validity(self) -> None:
        """Check the validity of each beneficiaries in the queryset.

        Adds errors to `self.total["errors"]` if any beneficiaries is invalid.
        """
        for item in self.queryset:
            if not item.is_valid():
                self.total["errors"].append(f"{self.model.__name__} #{item.pk} invalid")
            if self.has_members:
                for ind in item.members.all():
                    if not ind.is_valid():
                        self.total["errors"].append(f"Ind #{ind.pk} invalid")

    def rdi_create(self) -> None:
        """Create a new RDI record in the external system.

        Sets `self.rdi_id` if the creation is successful.
        """
        path = f"{self.base_path}create/"
        data = {"name": self.batch_name, "program": self.program_id}
        if response := self.safe_post(path, data, "Error creating RDI"):
            self.rdi_id = response.get("id")

    def rdi_push(self) -> None:
        """
        Pushes a batch of beneficiaries data to the external RDI system.

        Adds errors to `self.total["errors"]` if `rdi_id` is not set.
        Successfully pushed records are marked as removed.
        """
        if self.rdi_id is None:
            self.total["errors"].append("Cannot push data: rdi_id is not set")
            return
        batch_ids, batch_data = self.prepare_batch()
        path = f"{self.base_path}{self.rdi_id}/{self.push_endpoint}"
        if successful_ids := self.process_batch_response(
            self.safe_post(path, batch_data, "Error pushing data"),
            batch_ids,
        ):
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

    def prepare_batch(self) -> tuple[list[int], list[dict]]:
        """
        Prepare a batch of household/individual data for API submission.

        Returns:
            tuple[list[int], list[dict]]: A tuple of household/individual IDs and transformed data.

        """
        ids, data = [], []
        for item in self.queryset:
            ids.append(item.id)
            data.append(
                {**map_fields(item.flex_fields), "members": [map_fields(m.flex_fields) for m in item.members.all()]}
                if self.has_members
                else map_fields(item.flex_fields)
            )
        return ids, data

    def process_batch_response(self, response: dict | None, batch_ids: list[int]) -> list[int]:
        """
        Process the API response for a batch push operation.

        Args:
            response (dict | None): API response.
            batch_ids (list[int]): List of IDs for the batch that was pushed.

        Returns:
            list[int]: List of successfully processed IDs.

        """
        match response:
            case {"processed": int(p), "accepted": int(a)} if p == a == len(batch_ids):
                self.total["households"] = self.total.get("households", 0) + a
                return batch_ids
            case {"id": str(_rdi_id), "people": list(_batch_ids)} if _rdi_id == self.rdi_id and len(_batch_ids) == len(
                batch_ids
            ):
                self.total["people"] = self.total.get("people", 0) + len(_batch_ids)
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
        Mark successfully pushed beneficiaries as removed in the database.

        Args:
            successful_ids (list[int]): List of successfully pushed beneficiaries IDs.

        """
        try:
            with transaction.atomic():
                items = self.model.objects.filter(id__in=successful_ids)
                if self.has_members:
                    items = items.prefetch_related("members")
                for item in items:
                    if item.removed:
                        self.total["errors"].append(f"{self.model.__name__} #{item.id} already marked as removed")
                    else:
                        item.removed = True
                        item.save(update_fields=["removed"])
                    if self.has_members:
                        for ind in item.members.all():
                            if ind.removed:
                                self.total["errors"].append(f"Individual #{ind.id} already marked as removed")
                            else:
                                ind.removed = True
                                ind.save(update_fields=["removed"])
        except (DatabaseError, Exception) as e:
            self.total["errors"].append(f"Failed to mark IDs {successful_ids} as removed: {e}")


def push_to_hope_core(job: AsyncJob) -> dict[str, Any]:
    """
    Execute the data push workflow for a given job, performing validation, creation, data pushing, and finalization.

    Args:
        job (AsyncJob): The job configuration containing relevant identifiers and parameters.

    Returns:
        dict[str, Any]: Summary of the operation including processed beneficiaries and errors.

    """

    def steps() -> Iterator[Callable[[], None]]:
        """Yield steps for pushing beneficiaries data in batches."""
        yield processor.rdi_create
        for batch_pks in batched(job.config["pks"], HOUSEHOLD_PUSH_BATCH_SIZE):
            processor.set_queryset(batch_pks)
            yield from (processor.check_beneficiaries_validity, processor.rdi_push)
        yield processor.rdi_complete

    if job.program.beneficiary_group is None:
        return {"errors": ["Cannot proceed: beneficiary_group is not set"]}

    processor = PushProcessor(
        co_slug=job.program.country_office.slug,
        batch_name=job.config.get("batch_name"),
        program_id=job.program.hope_id,
        master_detail=job.program.beneficiary_group.master_detail,
    )

    for step in steps():
        step()
        if processor.total["errors"]:
            return processor.total
    return processor.total
