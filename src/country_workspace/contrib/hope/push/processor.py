from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from functools import cached_property
from itertools import batched
from typing import Any
from uuid import UUID

from django.db.models import QuerySet

from country_workspace.contrib.dedup_engine import make_dedup_client
from country_workspace.contrib.hope.constants import PUSH_BATCH_SIZE
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual

from country_workspace.contrib.hope.constants import IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE
from country_workspace.exceptions import RemoteError
from country_workspace.models import Rdp
from .config import ROLE_FIELDS, Serializer, ERROR_CONFIG, PushWorkflowConfig
from .mappings import load_mapping_from_api, map_members, map_role_value
from .repository import (
    qs_individuals_for_rdp,
    preflight_errors,
    preflight_exclude_rdp_ids,
    rdp_for_dedup,
    serializer_for_program,
    # set_rdp_dedup_state,
    set_rdp_deduplication_set_id,
)
from .transport import HopeApi


class ProcessorBase:
    """Shared processor primitives."""

    PREFIX: str = "Processor"

    def __init__(self) -> None:
        self.total: dict[str, Any] = {"errors": []}

    @property
    def has_errors(self) -> bool:
        """Return True when at least one error was collected."""
        return bool(self.total.get("errors"))

    @staticmethod
    def _ids_hint(ids: Sequence[int]) -> str:
        """Return a short ids hint suitable for logs."""
        limit = ERROR_CONFIG.MAX_IDS_HINT
        if not ids:
            return "[]"
        if len(ids) <= limit:
            return str(ids)
        head = ", ".join(map(str, ids[:limit]))
        return f"[{head}, …]"

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

    def _fmt_fail(
        self,
        subject: str,
        msg: str,
        *,
        ids: Sequence[int] | None = None,
        response: object | None = None,
    ) -> str:
        ids_part = f" ids={self._ids_hint(ids)}" if ids is not None else ""
        line = f"{self.PREFIX}: {subject}: {msg}{ids_part}"
        return f"{line}. Response: {response}" if response is not None else line

    def fail(
        self,
        subject: str,
        msg: str,
        *,
        ids: Sequence[int] | None = None,
        response: object | None = None,
    ) -> None:
        self._err(self._fmt_fail(subject, msg, ids=ids, response=response))

    def try_remote(
        self,
        subject: str,
        fn: Callable[[], Any],
        *,
        ids: Sequence[int] | None = None,
    ) -> Any | None:
        try:
            return fn()
        except RemoteError as e:
            self.fail(subject, f"request failed. {e}", ids=ids)
            return None

    def run_remote(
        self,
        subject: str,
        fn: Callable[[], object],
        *,
        ids: Sequence[int] | None = None,
    ) -> bool:
        try:
            fn()
        except RemoteError as e:
            self.fail(subject, f"request failed. {e}", ids=ids)
            return False
        return True


class PushProcessor(ProcessorBase):
    """Push pipeline: validate, prepare, send and track results via Hope API."""

    PREFIX = "HopePush"

    def __init__(self, config: PushWorkflowConfig) -> None:
        super().__init__()
        self.api = HopeApi(co_slug=config["co_slug"])
        self.batch_name: str = config["batch_name"]
        self.hope_rdi_id: str | None = None
        self.imported_by_email: str = config["imported_by_email"]
        self.ind_id_map: dict[int, str] = {}
        self.master_detail: bool = config["master_detail"]
        self.pks: list[int] = config["pks"]
        self.program_hope_id: str = config["program_hope_id"]
        self.queryset: QuerySet | None = None
        self.rdp_id: int | None = config.get("rdp_id")

    @cached_property
    def serializer(self) -> Serializer:
        """Return a callable that serializes rows for the current program (cached per run)."""
        return serializer_for_program(self.program_hope_id)

    def preflight(self) -> None:
        """Validate selected beneficiaries before creating/pushing RDP."""
        for msg in preflight_errors(
            pks=self.pks,
            master_detail=self.master_detail,
            exclude_rdp_ids=preflight_exclude_rdp_ids(rdp_id=self.rdp_id),
        ):
            self.fail("Preflight", msg)

    def rdi_complete(self) -> None:
        if not self.hope_rdi_id:
            self.fail("RDI", "can't complete: hope_rdi_id is not set")
            return
        self.run_remote("RDI", lambda: self.api.complete_rdi(self.hope_rdi_id))

    def rdi_create(self) -> None:
        payload = {
            "name": self.batch_name,
            "program": self.program_hope_id,
            "imported_by_email": self.imported_by_email,
        }
        resp = self.try_remote("RDI", lambda: self.api.create_rdi(payload))
        if resp is None:
            return

        if "id" not in resp or not resp.get("id"):
            self.fail("RDI", "can't create: no id in response", response=resp)
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

    def _process_households_response(self, response: dict, batch_ids: list[int]) -> None:
        if self._resp_err("Households", response, batch_ids):
            return
        expected = len(batch_ids)
        match response:
            case {"processed": p, "accepted": a} if isinstance(p, int) and isinstance(a, int):
                if p != a or a != expected:
                    self.fail(
                        "Households",
                        f"accepted mismatch processed={p} accepted={a} expected={expected}",
                        ids=batch_ids,
                        response=response,
                    )
                    return
                self.total["households"] = self.total.get("households", 0) + a
            case _:
                self.fail("Households", "unexpected response", ids=batch_ids, response=response)

    def _process_individuals_response(self, response: dict, batch_ids: list[int]) -> None:
        if self._resp_err("Individuals", response, batch_ids):
            return
        expected = len(batch_ids)
        match response:
            case {"processed": p, "accepted": a, "individual_id_mapping": mapping} if (
                isinstance(p, int) and isinstance(a, int) and isinstance(mapping, dict)
            ):
                if p != a or a != expected:
                    self.fail(
                        "Individuals",
                        f"accepted mismatch processed={p} accepted={a} expected={expected}",
                        ids=batch_ids,
                        response=response,
                    )
                self.total["individuals"] = self.total.get("individuals", 0) + a
                self.ind_id_map |= load_mapping_from_api(mapping, self._err)
            case _:
                self.fail("Individuals", "unexpected response", ids=batch_ids, response=response)

    def _process_people_response(self, response: dict, batch_ids: list[int]) -> None:
        if self._resp_err("People", response, batch_ids):
            return
        expected = len(batch_ids)
        match response:
            case {"id": hope_rdi_id, "people": people} if isinstance(people, list):
                if hope_rdi_id != self.hope_rdi_id:
                    self.fail(
                        "People",
                        f"rdi mismatch got={hope_rdi_id} expected={self.hope_rdi_id}",
                        ids=batch_ids,
                        response=response,
                    )
                    return
                if len(people) != expected:
                    self.fail(
                        "People",
                        f"people length mismatch got={len(people)} expected={expected}",
                        ids=batch_ids,
                        response=response,
                    )
                    return
                self.total["people"] = self.total.get("people", 0) + expected
            case _:
                self.fail("People", "unexpected response", ids=batch_ids, response=response)

    def _push_batched(
        self,
        name: str,
        prepare: Callable[[Iterable[Any]], tuple[list[int], list[dict]]],
        post: Callable[[str, list[dict]], dict[str, Any]],
        process: Callable[[dict, list[int]], None],
    ) -> None:
        """Iterate over QuerySet batches -> prepare batch -> POST -> process response."""
        if not self.hope_rdi_id:
            self.fail(name, "can't push: hope_rdi_id is not set")
            return
        if self.queryset is None:
            self.fail(name, "can't push: queryset is not set")
            return

        for batch in batched(self.queryset.iterator(chunk_size=PUSH_BATCH_SIZE * 5), PUSH_BATCH_SIZE):
            ids, payload = prepare(batch)
            if not ids:
                continue
            resp = self.try_remote(name, lambda payload=payload: post(self.hope_rdi_id, payload), ids=ids)
            if resp is None:
                continue
            process(resp, ids)

    def _resp_err(self, name: str, response: dict, batch_ids: list[int]) -> bool:
        if not response.get("errors"):
            return False

        log_resp = response
        results = response.get("results")

        if isinstance(results, list):

            def looks_accepted(item: object) -> bool:
                return (
                    isinstance(item, dict)
                    and "pk" in item
                    and not any(isinstance(v, (list, dict)) for v in item.values())
                )

            log_resp = {k: response.get(k) for k in ("id", "processed", "accepted", "errors")}
            log_resp["results"] = [item for item in results if not looks_accepted(item)]
            log_resp["_log_view"] = "errors_only"

        self.fail(name, "remote returned errors", ids=batch_ids, response=log_resp)
        return True

    @contextmanager
    def _using_qs(self, qs: QuerySet) -> Iterator[None]:
        """Temporarily set self.queryset to qs during a step execution."""
        prev = self.queryset
        self.queryset = qs
        try:
            yield
        finally:
            self.queryset = prev


class DedupProcessor(ProcessorBase):
    """Dedup pipeline: collect images, create set, upload and start processing."""

    PREFIX = "Dedup"

    def __init__(self, *, rdp_id: int) -> None:
        super().__init__()
        self.rdp = rdp_for_dedup(pk=rdp_id)
        self.program_unicef_id = self.rdp.program.unicef_id

    def run(self) -> None:
        """Execute dedup workflow; collect errors in total."""
        if self.rdp.status != Rdp.PushStatus.PENDING:
            self.fail("RDP", f"can not run dedup in status={self.rdp.status}")
        if self.has_errors:
            return

        self.total |= {"rdp_id": self.rdp.pk, "program": self.program_unicef_id}

        image_batches = (list(batch) for batch in batched(self._iter_images(), IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE))
        first_batch = next(image_batches, None)
        if first_batch is None:
            self.fail("Images", "no valid photos found")
            self.total["images_sent"] = 0
            self.total["deduplication_set_id"] = None
            return

        ds_id, images_sent = self.deduplicate(first_batch, image_batches)
        self.total["images_sent"] = images_sent
        self.total["deduplication_set_id"] = str(ds_id) if ds_id else None

    def _iter_images(self) -> Iterator[dict[str, str]]:
        """Yield DedupEngine images payload from RDP individuals."""
        rows = qs_individuals_for_rdp(rdp=self.rdp).values_list("id", "flex_fields__photo")
        for pk, photo in rows.iterator(chunk_size=IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE * 5):
            if isinstance(photo, str) and (photo := photo.strip()):
                yield {"reference_pk": str(pk), "filename": photo}

    def create_deduplication_set(self, client: Any) -> UUID | None:
        payload = self.try_remote("create_deduplication_set", client.create_deduplication_set)
        if payload is None:
            return None

        raw_id = payload.get("id")
        if not isinstance(raw_id, str) or not raw_id:
            self.fail("create_deduplication_set", "response has no valid id", response=payload)
            return None

        try:
            return UUID(raw_id)
        except ValueError as e:
            self.fail("create_deduplication_set", f"returned invalid UUID {raw_id!r}: {e}", response=payload)
            return None

    def upload_images(
        self,
        client: Any,
        first_batch: list[dict[str, str]],
        image_batches: Iterator[list[dict[str, str]]],
    ) -> tuple[bool, int]:
        """Upload image batches and return success flag with sent images count."""
        images_sent = 0
        batch = first_batch

        for next_batch in image_batches:
            if not self.run_remote("create_images", lambda batch=batch: client.create_images(batch, last=False)):
                return False, images_sent
            images_sent += len(batch)
            batch = next_batch

        if not self.run_remote("create_images", lambda batch=batch: client.create_images(batch, last=True)):
            return False, images_sent

        return True, images_sent + len(batch)

    def deduplicate(
        self, first_batch: list[dict[str, str]], image_batches: Iterator[list[dict[str, str]]]
    ) -> tuple[UUID | None, int]:
        """Run remote DedupEngine steps and return deduplication_set_id with sent images count."""
        with make_dedup_client(self.program_unicef_id) as client:
            can_create = self.try_remote("can_create_deduplication_set", client.can_create_deduplication_set)
            if can_create is not True:
                if can_create is False:
                    self.fail("RDP", "can not run dedup while another deduplication set is active")
                return None, 0

            ds_id = self.create_deduplication_set(client)
            if ds_id is None:
                return None, 0

            set_rdp_deduplication_set_id(rdp_id=self.rdp.pk, deduplication_set_id=ds_id)

            uploaded, images_sent = self.upload_images(client, first_batch, image_batches)
            if not uploaded:
                return ds_id, images_sent

            if not self.run_remote("process", client.process):
                return ds_id, images_sent

            return ds_id, images_sent
