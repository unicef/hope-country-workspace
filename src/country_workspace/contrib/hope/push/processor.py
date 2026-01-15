from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from functools import cached_property
from itertools import batched
from typing import Any

from django.db.models import QuerySet

from country_workspace.contrib.hope.constants import PUSH_BATCH_SIZE
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual

from .config import ROLE_FIELDS, Serializer, ERROR_CONFIG, PushWorkflowConfig
from .mappings import load_mapping_from_api, map_members, map_role_value
from .repository import serializer_for_program, preflight_errors
from .transport import HopeApi


class PushProcessor:
    """Push pipeline: validate, prepare, send and track results via Hope API."""

    def __init__(self, config: PushWorkflowConfig) -> None:
        self.api = HopeApi(co_slug=config["co_slug"], err=self._err)
        self.batch_name: str = config["batch_name"]
        self.hope_rdi_id: str | None = None
        self.imported_by_email: str = config["imported_by_email"]
        self.ind_id_map: dict[int, str] = {}
        self.master_detail: bool = config["master_detail"]
        self.pks: list[int] = config["pks"]
        self.program_hope_id: str = config["program_hope_id"]
        self.queryset: QuerySet | None = None
        self.rdp_id: int | None = config.get("rdp_id")
        self.total: dict[str, Any] = {"errors": []}

    @cached_property
    def serializer(self) -> Serializer:
        """Return a callable that serializes rows for the current program (cached per run)."""
        return serializer_for_program(self.program_hope_id)

    def preflight(self) -> None:
        """Validate selected beneficiaries before creating/pushing RDP."""
        for msg in preflight_errors(pks=self.pks, master_detail=self.master_detail, exclude_rdp_id=self.rdp_id):
            self._err(msg)

    def rdi_complete(self) -> None:
        """Finalize the remote RDI."""
        if not self.hope_rdi_id:
            self._err("RDI: can't complete: hope_rdi_id is not set")
            return
        self.api.complete_rdi(self.hope_rdi_id)

    def rdi_create(self) -> None:
        """Create the remote RDI and set self.hope_rdi_id on success."""
        payload = {
            "name": self.batch_name,
            "program": self.program_hope_id,
            "imported_by_email": self.imported_by_email,
        }
        resp = self.api.create_rdi(payload)
        if not resp or "id" not in resp or not resp.get("id"):
            self._err("RDI: can't create: no id in response")
            return
        self.hope_rdi_id = resp["id"]

    def rdi_push_households(self) -> None:
        """Push households in batches."""
        self._push_batched(
            "Households", self._prepare_households_batch, self.api.post_households, self._process_households_response
        )

    def rdi_push_individuals(self) -> None:
        """Push individuals in batches; also builds the IND id mapping."""
        self._push_batched(
            "Individuals",
            self._prepare_individuals_batch,
            self.api.post_individuals,
            self._process_individuals_response,
        )

    def rdi_push_people(self) -> None:
        """Push people in batches."""
        self._push_batched("People", self._prepare_people_batch, self.api.post_people, self._process_people_response)

    def run_with(self, qs: QuerySet, step: Callable) -> None:
        """Execute a step with the given QuerySet set as self.queryset."""
        with self._using_qs(qs):
            step()

    def _err(self, msg: str) -> None:
        """Append an error into total['errors']; truncate long text; cap the list with a marker."""
        errors: list[str] = self.total["errors"]
        if errors and errors[-1] == ERROR_CONFIG.MARKER:
            return
        if len(errors) >= ERROR_CONFIG.MAX_ERRORS - 1:
            errors.append(ERROR_CONFIG.MARKER)
            return
        if len(msg) > ERROR_CONFIG.MAX_ERROR_LEN:
            msg = f"{msg[: ERROR_CONFIG.MAX_ERROR_LEN - 1]}…"
        errors.append(msg)

    def _prepare_households_batch(self, batch: Iterable[CountryHousehold]) -> tuple[list[int], list[dict]]:
        """Return (ids, payload) for a households batch: roles mapped, members resolved."""
        ids, rows = [], []
        for hh in batch:
            ids.append(hh.id)
            flex_fields = hh.apply_grouping()
            for key in ROLE_FIELDS:
                flex_fields[key] = map_role_value(self.ind_id_map, self._err, hh.pk, key, flex_fields.get(key))
            prefetched = getattr(hh, "prefetched_members", None)
            member_ids = (
                [m.id for m in prefetched] if prefetched is not None else list(hh.members.values_list("id", flat=True))
            )
            flex_fields["members"] = map_members(self.ind_id_map, self._err, hh.pk, member_ids)
            flex_fields["originating_id"] = hh.originating_id
            rows.append({k: v for k, v in flex_fields.items() if v is not None})
        return ids, self.serializer(rows)

    def _prepare_individuals_batch(self, batch: Iterable[CountryIndividual]) -> tuple[list[int], list[dict]]:
        """Return (ids, payload) for an individuals batch; inject 'individual_id' per row."""
        rows = [ind.apply_grouping() | {"individual_id": ind.id, "originating_id": ind.originating_id} for ind in batch]
        ids = [row["individual_id"] for row in rows]
        return ids, self.serializer(rows)

    def _prepare_people_batch(self, batch: Iterable[CountryIndividual]) -> tuple[list[int], list[dict]]:
        """Return (ids, payload) for a people batch."""
        ids = [ind.id for ind in batch]
        rows = [ind.apply_grouping() | {"originating_id": ind.originating_id} for ind in batch]
        return ids, self.serializer(rows)

    def _process_households_response(self, response: dict | None, batch_ids: list[int]) -> None:
        """Update totals or log errors based on the households push response."""
        if self._resp_err("Households", response, batch_ids):
            return
        match response:
            case {"processed": p, "accepted": a} if (
                isinstance(p, int) and isinstance(a, int) and p == a == len(batch_ids)
            ):
                self.total["households"] = self.total.get("households", 0) + a
            case _:
                self._resp_unexpected("Households", batch_ids, response)

    def _process_individuals_response(self, response: dict | None, batch_ids: list[int]) -> None:
        """Update totals, refresh IND mapping or log errors based on individuals response."""
        if self._resp_err("Individuals", response, batch_ids):
            return
        match response:
            case {"processed": p, "accepted": a, "individual_id_mapping": mapping} if (
                isinstance(p, int) and isinstance(a, int) and isinstance(mapping, dict)
            ):
                if p != a or a != len(batch_ids):
                    self._err(f"Individuals - accepted mismatch processed for {batch_ids}: {response}")
                self.total["individuals"] = self.total.get("individuals", 0) + a
                self.ind_id_map |= load_mapping_from_api(mapping, self._err)
            case _:
                self._resp_unexpected("Individuals", batch_ids, response)

    def _process_people_response(self, response: dict | None, batch_ids: list[int]) -> None:
        """Update totals or log errors based on the people push response."""
        if self._resp_err("People", response, batch_ids):
            return
        expected = len(batch_ids)
        match response:
            case {"id": hope_rdi_id, "people": people} if (
                hope_rdi_id == self.hope_rdi_id and isinstance(people, list) and len(people) == expected
            ):
                self.total["people"] = self.total.get("people", 0) + expected
            case _:
                self._resp_unexpected("People", batch_ids, response)

    def _push_batched(
        self,
        name: str,
        prepare: Callable[[Iterable[Any]], tuple[list[int], list[dict]]],
        post: Callable[[str, list[dict]], dict[str, Any] | None],
        process: Callable[[dict | None, list[int]], None],
    ) -> None:
        """Iterate over QuerySet batches -> prepare batch -> POST -> process response."""
        if not self.hope_rdi_id:
            self._err(f"{name} - can't push: hope_rdi_id is not set")
            return
        if self.queryset is None:
            self._err(f"{name} - can't push: queryset is not set")
            return
        for batch in batched(self.queryset.iterator(chunk_size=PUSH_BATCH_SIZE * 5), PUSH_BATCH_SIZE):
            ids, payload = prepare(batch)
            if ids:
                resp = post(self.hope_rdi_id, payload)
                process(resp, ids)

    def _resp_err(self, name: str, response: dict | None, batch_ids: list[int]) -> bool:
        if response is None:
            self._err(f"{name} - batch failed for {batch_ids}")
            return True
        if isinstance(response, dict) and response.get("errors"):
            self._err(f"{name} - push error for {batch_ids}: {response}")
            return True
        return False

    def _resp_unexpected(self, name: str, batch_ids: list[int], response: object) -> None:
        self._err(f"{name} - unexpected response for {batch_ids}: {response}")

    @contextmanager
    def _using_qs(self, qs: QuerySet) -> Iterator[None]:
        """Temporarily set self.queryset to qs during a step execution."""
        prev = self.queryset
        self.queryset = qs
        try:
            yield
        finally:
            self.queryset = prev
