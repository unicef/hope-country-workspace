from typing import TypedDict, Protocol, TypeVar, Generic
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest
from admin_extra_buttons.api import button

from ..contrib.hope.sync.context_programs import sync_context_programs, SyncStep as ContextProgramsSyncStep
from ..contrib.hope.sync.context_geo import sync_context_geo, SyncStep as ContextGeoSyncStep


T_SyncStep = TypeVar("T_SyncStep", bound=ContextProgramsSyncStep | ContextGeoSyncStep)
type SyncHandlerResp = dict[str, list[str] | dict[str, int]]


class SyncHandler(Protocol, Generic[T_SyncStep]):
    def sync(self, step: T_SyncStep) -> SyncHandlerResp:
        pass


class ContextProgramsSyncHandler:
    def sync(self, step: ContextProgramsSyncStep) -> SyncHandlerResp:
        return sync_context_programs(step)


class ContextGeoSyncHandler:
    def sync(self, step: ContextGeoSyncStep) -> SyncHandlerResp:
        return sync_context_geo(step)


class SyncConfig(TypedDict):
    model: type[Model]
    step: T_SyncStep
    sync_handler: SyncHandler


class SyncAdminMixin:
    sync_config: SyncConfig

    @button()
    def sync(self, request: HttpRequest) -> None:
        totals = self.sync_config["sync_handler"].sync(step=self.sync_config["step"])
        if errors := totals.get("errors"):
            self.message_user(request, "; ".join(errors), level=messages.ERROR)
        else:
            info = totals[self.sync_config["model"]._meta.model_name]
            self.message_user(request, f"{info['add']} created - {info['upd']} updated", level=messages.SUCCESS)
