import factory
from django.utils import timezone

from country_workspace.models.rdp import Rdp
from country_workspace.workspaces.models import CountryRdp

from .base import AutoRegisterModelFactory
from .program import ProgramFactory
from .user import UserFactory


class RdpFactory(AutoRegisterModelFactory):
    pushed_by = factory.SubFactory(UserFactory)
    push_date = factory.LazyFunction(timezone.now)
    name = factory.Sequence(lambda n: f"RDP {n}")
    status = Rdp.PushStatus.PENDING
    hope_rdi_id = factory.Sequence(lambda n: f"hope-rdi-{n}")
    program = factory.SubFactory(ProgramFactory)
    deduplication_set_id = None
    is_dedup_settings_locked = False
    is_push_locked = False
    operation_log = factory.LazyFunction(list)

    class Meta:
        model = Rdp

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        kwargs["country_office"] = kwargs["program"].country_office
        return super()._create(model_class, *args, **kwargs)


class CountryRdpFactory(RdpFactory):
    class Meta:
        model = CountryRdp
        django_get_or_create = ("name", "program")
