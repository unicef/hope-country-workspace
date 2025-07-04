from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from itertools import batched
from json import JSONDecodeError
from typing import Any, TypedDict, ReadOnly

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from requests.exceptions import RequestException

from country_workspace.contrib.hope.client import HopeClient
from country_workspace.exceptions import RemoteError
from country_workspace.models import AsyncJob, Rdp
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual
from country_workspace.utils.fields import map_fields


type Beneficiary = CountryHousehold | CountryIndividual


class PushConfig(TypedDict):
    batch_name: ReadOnly[str]
    batch_size: ReadOnly[int]
    co_slug: ReadOnly[str]
    country_office_id: ReadOnly[int]
    imported_by_email: ReadOnly[str]
    master_detail: ReadOnly[bool]
    pks: ReadOnly[list[int]]
    program_id: ReadOnly[int]
    program_hope_id: ReadOnly[str]
    pushed_by_id: ReadOnly[int]


class WorkflowConfig(PushConfig):
    """Configuration for the push workflow, including RDP ID."""

    rdp_id: int


class BatchErrorHandlerMixin:
    """Mixin for handling API batch errors with type safety."""

    def save_batch_errors_to_beneficiaries(self, response: dict, batch_ids: list[int]) -> None:
        """Save API errors to beneficiary records."""
        try:
            if self.master_detail:
                beneficiaries = self._get_ordered_beneficiaries(batch_ids)
                for hh_data in response.get("households", []):
                    for hh_key, hh_errors_list in hh_data.items():
                        if (hh := self._get_object_by_key(beneficiaries, hh_key)) is None:
                            continue
                        for errors_dict in hh_errors_list:
                            self._process_household_errors(hh, errors_dict)
            else:
                self._process_people_errors(response, batch_ids)
        except Exception as e:  # noqa: BLE001
            self._add_error(f"Failed to save errors to beneficiaries: {e}")

    def _process_household_errors(self, hh: CountryHousehold, errors_dict: dict) -> None:
        """Process errors for household and its members."""
        if hh_errors := {k: v for k, v in errors_dict.items() if k != "members"}:
            self._save_errors_to_object(hh, hh_errors)
        if members_errors := errors_dict.get("members"):
            members = list(hh.members.all())
            for member_key, member_errors in members_errors.items():
                if (member := self._get_object_by_key(members, member_key)) is not None:
                    self._save_errors_to_object(member, member_errors[0])

    def _process_people_errors(self, response: list, batch_ids: list[int]) -> None:
        """Process errors for people endpoint (individuals only)."""
        beneficiaries = self._get_ordered_beneficiaries(batch_ids)
        for i, errors_dict in enumerate(response):
            if i < len(beneficiaries) and errors_dict:
                self._save_errors_to_object(beneficiaries[i], errors_dict)

    def _get_ordered_beneficiaries(self, batch_ids: list[int]) -> list[Beneficiary]:
        """Get beneficiaries in the same order as batch_ids."""
        objects = {obj.id: obj for obj in self.model.objects.filter(id__in=batch_ids)}
        missing = set(batch_ids) - objects.keys()
        if missing:
            self._add_error(f"{self.model.__name__} objects not found: {sorted(missing)}")
        return [objects[pk] for pk in batch_ids if pk in objects]

    def _get_object_by_key(self, objects: list, key: str) -> Beneficiary | None:
        """Extract object by key like 'Household #1' or 'Member #2'."""
        try:
            num = int(key.split("#")[1]) - 1
            if 0 <= num < len(objects):
                return objects[num]
        except (ValueError, IndexError):
            pass
        self._add_error(f"Invalid key: {key}")
        return None

    def _save_errors_to_object(self, obj: Beneficiary, errors: dict) -> None:
        """Save errors to a single object."""
        obj.errors = errors
        obj.last_checked = timezone.now()
        obj.save(update_fields=["errors", "last_checked"])

    def _add_error(self, message: str) -> None:
        """Add error message to total errors."""
        self.total.setdefault("errors", []).append(message)


@dataclass
class PushProcessor(BatchErrorHandlerMixin):
    """Handles pushing beneficiaries data to an external system through the HopeClient API."""

    batch_name: str
    co_slug: str
    imported_by_email: str
    master_detail: bool
    program_hope_id: str
    client: HopeClient = field(default_factory=HopeClient)
    rdp_id: int | None = None
    total: dict[str, Any] = field(default_factory=lambda: {"errors": []})
    model: type = field(init=False)
    push_endpoint: str = field(init=False)
    queryset: QuerySet = field(init=False)
    hope_rdi_id: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.model, self.push_endpoint = (
            (CountryHousehold, "push/lax/") if self.master_detail else (CountryIndividual, "push/people/")
        )
        self.base_path = f"{self.co_slug}/rdi/"
        self.queryset = self.model.objects.none()

    def set_queryset(self, pks: list[int]) -> None:
        """Set the queryset based on master_detail and provided pks."""
        qs = self.model.objects.filter(pk__in=pks)
        self.queryset = qs.prefetch_related("members") if self.master_detail else qs

    # TODO(Vitali): use FullHouseholdValidator (?)
    def check_beneficiaries_validity(self) -> None:
        """Check the validity of each beneficiaries in the queryset."""
        for item in self.queryset:
            self._validate_beneficiary(item, self.model.__name__)
            if self.master_detail:
                for ind in item.members.all():
                    self._validate_beneficiary(ind, "Ind")

    def _validate_beneficiary(self, obj: Beneficiary, prefix: str) -> None:
        """Validate a single beneficiary object."""
        if not obj.is_valid():
            self.total["errors"].append(f"{prefix} #{obj.pk} invalid")
        if obj.rdp.filter(status__in=[Rdp.PushStatus.PENDING, Rdp.PushStatus.SUCCESS]).exclude(pk=self.rdp_id).exists():
            self.total["errors"].append(f"{prefix} #{obj.pk} already in another RDP(s) (pending/success)")

    def rdi_create(self) -> None:
        """Create a new RDI record in the external system.

        Sets `self.hope_rdi_id` if the creation is successful.
        """
        path = f"{self.base_path}create/"
        data = {"name": self.batch_name, "program": self.program_hope_id, "imported_by_email": self.imported_by_email}
        if response := self.safe_post(path, data, "Error creating RDI"):
            self.hope_rdi_id = response.get("id")

    def rdi_push(self) -> None:
        """Push a batch of beneficiaries data to the external system as RDI."""
        if self.hope_rdi_id is None:
            self.total["errors"].append("Cannot push data: hope_rdi_id is not set")
            return
        batch_ids, batch_data = self.prepare_batch()
        if not batch_ids:
            self.total["errors"].append("No data to push")
            return
        path = f"{self.base_path}{self.hope_rdi_id}/{self.push_endpoint}"
        response = self.safe_post(path, batch_data, "Error pushing data")
        self.process_batch_response(response, batch_ids)

    def rdi_complete(self) -> None:
        """Mark the RDI push as completed in the external system."""
        if self.hope_rdi_id is None:
            self.total["errors"].append("Cannot complete RDI: hope_rdi_id is not set")
            return
        path = f"{self.base_path}{self.hope_rdi_id}/completed/"
        self.safe_post(path, None, "Error completing RDI")

    def safe_post(self, path: str, data: Any, error_msg: str) -> dict[str, Any] | None:
        """Send a POST request to the HopeClient API and handles errors."""
        try:
            return self.client.post(path, data)
        except (RequestException, JSONDecodeError, RemoteError) as e:
            self.total["errors"].append(f"{error_msg}: {e}")
            return None

    def prepare_batch(self) -> tuple[list[int], list[dict]]:
        """Prepare a batch of household/individual|people data for API submission."""
        ids, data = [], []
        for item in self.queryset:
            ids.append(item.id)
            data.append(
                {**map_fields(item.flex_fields), "members": [map_fields(m.flex_fields) for m in item.members.all()]}
                if self.master_detail
                else map_fields(item.flex_fields)
            )
        return ids, data

    def process_batch_response(self, response: dict | None, batch_ids: list[int]) -> list[int]:
        """Process the API response for a batch push operation."""
        match response:
            case {"processed": p, "accepted": a} if p == a == len(batch_ids):
                self.total["households"] = self.total.get("households", 0) + a
                return batch_ids
            case {"id": hope_rdi_id, "people": batch_list} if hope_rdi_id == self.hope_rdi_id and len(
                batch_list
            ) == len(batch_ids):
                self.total["people"] = self.total.get("people", 0) + len(batch_ids)
                return batch_ids
            case {"errors": e} if e:
                if e is True and "people" in response:
                    self.total["errors"].append(f"Error pushing data for IDs: {batch_ids} - {response}")
                    self.save_batch_errors_to_beneficiaries(response["people"], batch_ids)
                elif e > 0:
                    self.total["errors"].append(f"Error pushing data for IDs: {batch_ids} - {response}")
                    self.save_batch_errors_to_beneficiaries(response, batch_ids)
                else:
                    self.total["errors"].append(f"Unexpected error format for IDs: {batch_ids} - {response}")
            case None:
                self.total["errors"].append(f"Batch failed for IDs: {batch_ids}")
            case _:
                self.total["errors"].append(f"Unexpected response for IDs: {batch_ids} - {response}")
        return []


def create_rdp_records(config: PushConfig, job_id: int) -> int:
    """Create RDP records and related items in the database."""
    with transaction.atomic():
        rdp = Rdp.objects.create(
            country_office_id=config["country_office_id"],
            program_id=config["program_id"],
            name=config["batch_name"],
            pushed_by_id=config["pushed_by_id"],
            status=Rdp.PushStatus.PENDING,
        )
        rdp.add_beneficiaries(config["pks"], config["master_detail"])
        AsyncJob.objects.filter(id=job_id).update(rdp=rdp)
        return rdp.id


def create_processor(config: WorkflowConfig) -> PushProcessor:
    """Create and configure PushProcessor."""
    return PushProcessor(
        co_slug=config["co_slug"],
        batch_name=config["batch_name"],
        program_hope_id=config["program_hope_id"],
        master_detail=config["master_detail"],
        imported_by_email=config["imported_by_email"],
        rdp_id=config["rdp_id"],
    )


def complete_rdp(rdp_id: int, status: Rdp.PushStatus, hope_rdi_id: str) -> Rdp:
    """Complete RDP with given status and update the hope_rdi_id."""
    with transaction.atomic():
        rdp = Rdp.objects.select_for_update().get(id=rdp_id)
        rdp.status = status
        rdp.hope_rdi_id = hope_rdi_id
        rdp.save(update_fields=["status", "hope_rdi_id"])
        return rdp


def mark_rdp_beneficiaries_removed(rdp: Rdp, is_master_detail: bool) -> None:
    """Mark all beneficiaries related to RDP as removed."""
    if is_master_detail:
        rdp.households.update(removed=True)
        CountryIndividual.objects.filter(household__rdp=rdp).update(removed=True)
    else:
        rdp.individuals.update(removed=True)


def push_to_hope_core(job: AsyncJob) -> dict[str, Any]:
    """Execute the data push workflow for a given job."""

    def steps() -> Iterator[Callable[[], None]]:
        """Yield steps for pushing beneficiaries data in batches."""
        yield processor.rdi_create
        for batch_pks in batched(config["pks"], config["batch_size"]):
            processor.set_queryset(batch_pks)
            yield from (processor.check_beneficiaries_validity, processor.rdi_push)
        yield processor.rdi_complete

    if job.program.beneficiary_group is None:
        return {"errors": ["Cannot proceed: beneficiary_group is not set"]}

    rdp_id = create_rdp_records(job.config, job.id)
    config: WorkflowConfig = {**job.config, "rdp_id": rdp_id}
    processor = create_processor(config)
    for step in steps():
        step()
        if processor.total["errors"]:
            complete_rdp(rdp_id, Rdp.PushStatus.FAILURE, processor.hope_rdi_id or "N/A")
            return processor.total

    with transaction.atomic():
        rdp = complete_rdp(rdp_id, Rdp.PushStatus.SUCCESS, processor.hope_rdi_id)
        mark_rdp_beneficiaries_removed(rdp, config["master_detail"])

    return processor.total
