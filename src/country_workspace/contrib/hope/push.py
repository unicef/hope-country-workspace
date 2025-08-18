from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import cached_property
from itertools import batched
from json import JSONDecodeError
from typing import Any, TypedDict, ReadOnly
import base64

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from requests.exceptions import RequestException

from country_workspace.contrib.hope.client import HopeClient
from country_workspace.contrib.hope.constants import (
    DOCUMENT_TYPES,
    ACCOUNT_TYPES,
    PUSH_BATCH_SIZE,
    INDIVIDUAL_FIELD_MAPPINGS,
    HOUSEHOLD_FIELD_MAPPINGS,
    ADMIN_AREA_MAPPINGS,
    INDIVIDUAL_REQUIRED_FIELDS,
    DOCUMENT_TYPE_MAPPING,
    ACCOUNT_TYPE_MAPPING,
)
from country_workspace.exceptions import RemoteError
from country_workspace.models import AsyncJob, Rdp, Program
from country_workspace.models.base import Validable
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual

type Beneficiary = CountryHousehold | CountryIndividual


class PushConfig(TypedDict):
    batch_name: ReadOnly[str]
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
    individual_id_mapping: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        # Updated endpoints to match HOPE Core API
        self.model, self.push_endpoint = (
            (CountryHousehold, "push/lax/households")
            if self.master_detail
            else (CountryIndividual, "push/lax/individuals")
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

    def rdi_push_individuals(self) -> None:
        """Push individuals data to the external system."""
        if self.hope_rdi_id is None:
            self.total["errors"].append("Cannot push individuals: hope_rdi_id is not set")
            return

        # Get all individuals from households if in master_detail mode
        if self.master_detail:
            individual_pks = set()
            for household in self.queryset:
                individual_pks.update(household.members.values_list("pk", flat=True))
            individuals_qs = CountryIndividual.objects.filter(pk__in=individual_pks)
        else:
            individuals_qs = self.queryset

        if not individuals_qs.exists():
            self.total["errors"].append("No individuals to push")
            return

        # Validate individuals before pushing
        for individual in individuals_qs:
            self._validate_beneficiary(individual, "Ind")

        if self.total["errors"]:
            return

        # Process individuals in batches
        for batch_pks in batched(individuals_qs.values_list("pk", flat=True), PUSH_BATCH_SIZE):
            batch_individuals = CountryIndividual.objects.filter(pk__in=batch_pks)
            batch_data = [self._transform_individual_data(ind) for ind in batch_individuals]

            path = f"{self.base_path}{self.hope_rdi_id}/push/lax/individuals"
            response = self.safe_post(path, batch_data, "Error pushing individuals")
            self._process_individuals_response(response, list(batch_pks))

    def rdi_push_households(self) -> None:
        """Push households data to the external system."""
        if self.hope_rdi_id is None:
            self.total["errors"].append("Cannot push households: hope_rdi_id is not set")
            return

        if not self.master_detail:
            self.total["errors"].append("Cannot push households in individual mode")
            return

        batch_ids, batch_data = self.prepare_household_batch()
        if not batch_ids:
            self.total["errors"].append("No household data to push")
            return

        path = f"{self.base_path}{self.hope_rdi_id}/push/lax/households"
        response = self.safe_post(path, batch_data, "Error pushing households")
        self._process_households_response(response, batch_ids)

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

    @cached_property
    def program(self) -> Program:
        return Program.objects.get(hope_id=self.program_hope_id)

    @staticmethod
    def _set_types(item: Validable) -> None:
        for _type in DOCUMENT_TYPES + ACCOUNT_TYPES:
            prefix = f"{_type}_"
            type_field = f"{prefix}type" if _type in DOCUMENT_TYPES else f"{prefix}account_type"
            if type_field in item.flex_fields:
                item.flex_fields[type_field] = _type

    def _validate_individual_data(self, individual: CountryIndividual) -> list[str]:
        errors = []
        flex_fields = individual.apply_grouping()

        if not flex_fields.get("birth_date"):
            errors.append(f"Individual {individual.pk}: birth_date is required")

        if "documents" in flex_fields:
            for _i, doc in enumerate(flex_fields["documents"]):
                doc_type = doc.get("type")
                if doc_type and doc_type not in DOCUMENT_TYPE_MAPPING:
                    errors.append(f"Individual {individual.pk}: Invalid document type '{doc_type}'")

        if "accounts" in flex_fields:
            for _i, acc in enumerate(flex_fields["accounts"]):
                acc_type = acc.get("account_type")
                if acc_type and acc_type not in ACCOUNT_TYPE_MAPPING:
                    errors.append(f"Individual {individual.pk}: Invalid account type '{acc_type}'")

        return errors

    def _transform_individual_data(self, individual: CountryIndividual) -> dict:
        validation_errors = self._validate_individual_data(individual)
        if validation_errors:
            for error in validation_errors:
                self._add_error(error)
            return {}

        self._set_types(individual)

        flex_fields = individual.apply_grouping()

        transformed = {"individual_id": str(individual.pk), "flex_fields": flex_fields}

        for source_field, target_field in INDIVIDUAL_FIELD_MAPPINGS.items():
            if value := flex_fields.get(source_field):
                transformed[target_field] = value

        for required_field, default_value in INDIVIDUAL_REQUIRED_FIELDS.items():
            if required_field not in transformed:
                transformed[required_field] = default_value

        if "documents" in flex_fields:
            transformed["documents"] = self._transform_documents(flex_fields["documents"])

        if "accounts" in flex_fields:
            transformed["accounts"] = self._transform_accounts(flex_fields["accounts"])

        if hasattr(individual, "photo") and individual.photo:
            transformed["photo"] = self._encode_photo(individual.photo)

        return transformed

    def _transform_household_data(self, household: CountryHousehold) -> dict:
        flex_fields = household.apply_grouping()

        transformed = {"flex_fields": flex_fields}

        self._apply_field_mappings(transformed, flex_fields)
        self._apply_admin_area_mappings(transformed, flex_fields)
        self._map_individual_references(transformed, flex_fields, household)
        self._map_household_members(transformed, household)

        transformed.setdefault("consent_sharing", [])

        return transformed

    def _apply_field_mappings(self, transformed: dict, flex_fields: dict) -> None:
        for source_field, target_field in HOUSEHOLD_FIELD_MAPPINGS.items():
            if value := flex_fields.get(source_field):
                transformed[target_field] = value

    def _apply_admin_area_mappings(self, transformed: dict, flex_fields: dict) -> None:
        for source_field, target_field in ADMIN_AREA_MAPPINGS.items():
            if value := flex_fields.get(source_field):
                transformed[target_field] = value

    def _map_individual_references(self, transformed: dict, flex_fields: dict, household: CountryHousehold) -> None:
        if head_id := flex_fields.get("head_of_household_id"):
            unicef_id = self.individual_id_mapping.get(str(head_id))
            if unicef_id:
                transformed["head_of_household"] = unicef_id
            else:
                self._add_error(f"Household {household.pk}: head_of_household_id {head_id} not found in mapping")

        if primary_id := flex_fields.get("primary_collector_id"):
            unicef_id = self.individual_id_mapping.get(str(primary_id))
            if unicef_id:
                transformed["primary_collector"] = unicef_id
            else:
                self._add_error(f"Household {household.pk}: primary_collector_id {primary_id} not found in mapping")

        if alternate_id := flex_fields.get("alternate_collector_id"):
            unicef_id = self.individual_id_mapping.get(str(alternate_id))
            if unicef_id:
                transformed["alternate_collector"] = unicef_id

    def _map_household_members(self, transformed: dict, household: CountryHousehold) -> None:
        transformed["members"] = []
        for member in household.members.all():
            unicef_id = self.individual_id_mapping.get(str(member.pk))
            if unicef_id:
                transformed["members"].append(unicef_id)
            else:
                self._add_error(f"Household {household.pk}: member {member.pk} not found in mapping")

    def _transform_documents(self, documents: list[dict]) -> list[dict]:
        transformed_docs = []
        for doc in documents:
            doc_type = doc.get("type")
            if doc_type and doc_type not in DOCUMENT_TYPE_MAPPING:
                self._add_error(f"Invalid document type: {doc_type}")
                continue

            transformed_docs.append(
                {
                    "type": doc.get("type"),
                    "country": doc.get("country"),
                    "document_number": doc.get("document_number"),
                    "issuance_date": doc.get("issuance_date"),
                    "expiry_date": doc.get("expiry_date"),
                    "image": doc.get("image", ""),
                }
            )
        return transformed_docs

    def _transform_accounts(self, accounts: list[dict]) -> list[dict]:
        transformed_accounts = []
        for acc in accounts:
            acc_type = acc.get("account_type")
            if acc_type and acc_type not in ACCOUNT_TYPE_MAPPING:
                self._add_error(f"Invalid account type: {acc_type}")
                continue

            transformed_accounts.append(
                {
                    "account_type": acc.get("account_type"),
                    "number": acc.get("number", ""),
                    "financial_institution": acc.get("financial_institution"),
                    "data": acc.get("data", {}),
                }
            )
        return transformed_accounts

    def _encode_photo(self, photo_file: Any) -> str:
        try:
            if photo_file and hasattr(photo_file, "read"):
                photo_file.seek(0)
                return base64.b64encode(photo_file.read()).decode("utf-8")
        except (OSError, ValueError, AttributeError) as e:
            self.total.setdefault("warnings", []).append(f"Failed to encode photo: {e}")
        return ""

    def prepare_household_batch(self) -> tuple[list[int], list[dict]]:
        ids, data = [], []
        filter_none = lambda d: {k: v for k, v in d.items() if v is not None}

        for household in self.queryset:
            ids.append(household.id)
            household_data = self._transform_household_data(household)

            if not household_data:
                continue

            data.append(filter_none(household_data))

        return ids, self.program.serialize(data)

    def _process_individuals_response(self, response: dict | None, batch_ids: list[int]) -> None:
        if not response:
            self.total["errors"].append(f"Individuals batch failed for IDs: {batch_ids}")
            return

        processed = response.get("processed", 0)
        accepted = response.get("accepted", 0)
        errors = response.get("errors", 0)

        if processed == len(batch_ids) and accepted == len(batch_ids):
            self.total["people"] = self.total.get("people", 0) + accepted

            if individual_mapping := response.get("individual_id_mapping"):
                self.individual_id_mapping.update(individual_mapping)
        elif errors > 0:
            self.total["errors"].append(f"Individuals batch errors for IDs: {batch_ids}")
            if results := response.get("results"):
                self._process_validation_errors(results, batch_ids)

    def _process_households_response(self, response: dict | None, batch_ids: list[int]) -> None:
        if not response:
            self.total["errors"].append(f"Households batch failed for IDs: {batch_ids}")
            return

        processed = response.get("processed", 0)
        accepted = response.get("accepted", 0)
        errors = response.get("errors", 0)

        if processed == len(batch_ids) and accepted == len(batch_ids):
            self.total["households"] = self.total.get("households", 0) + accepted
        elif errors > 0:
            self.total["errors"].append(f"Households batch errors for IDs: {batch_ids}")
            if results := response.get("results"):
                self._process_validation_errors(results, batch_ids)

    def _process_validation_errors(self, results: list, batch_ids: list[int]) -> None:
        for i, result in enumerate(results):
            if i < len(batch_ids) and isinstance(result, dict) and result:
                self.total["errors"].append(f"Validation error for ID {batch_ids[i]}: {result}")

    def rdi_push(self) -> None:
        if self.master_detail:
            self.rdi_push_individuals()
            if not self.total["errors"]:
                self.rdi_push_households()
        else:
            self.rdi_push_individuals()

    def prepare_batch(self) -> tuple[list[int], list[dict]]:
        if self.master_detail:
            return self.prepare_household_batch()
        ids, data = [], []
        filter_none = lambda d: {k: v for k, v in d.items() if v is not None}
        for individual in self.queryset:
            ids.append(individual.id)
            individual_data = self._transform_individual_data(individual)
            if individual_data:
                data.append(filter_none(individual_data))
        return ids, self.program.serialize(data)

    def process_batch_response(self, response: dict | None, batch_ids: list[int]) -> list[int]:
        if self.master_detail:
            self._process_households_response(response, batch_ids)
        else:
            self._process_individuals_response(response, batch_ids)

        # Return processed IDs if successful
        if response and response.get("accepted", 0) == len(batch_ids):
            return batch_ids
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

        if config["master_detail"]:
            yield processor.rdi_push_individuals
            yield processor.rdi_push_households
        else:
            for batch_pks in batched(config["pks"], PUSH_BATCH_SIZE):
                processor.set_queryset(batch_pks)
                yield processor.rdi_push_individuals

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
