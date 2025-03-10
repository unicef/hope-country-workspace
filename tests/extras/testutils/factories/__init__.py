import importlib
import pkgutil
from pathlib import Path

from factory.django import DjangoModelFactory
from pytest_factoryboy import register

from .base import AutoRegisterModelFactory, TAutoRegisterModelFactory, factories_registry
from .batch import BatchFactory, CountryBatchFactory  # noqa
from .django_celery_beat import PeriodicTaskFactory  # noqa
from .household import CountryHouseholdFactory, HouseholdFactory  # noqa
from .individual import CountryIndividualFactory, IndividualFactory  # noqa
from .job import AsyncJobFactory  # noqa
from .locations import AreaFactory, AreaTypeFactory, CountryFactory  # noqa
from .office import OfficeFactory  # noqa
from .program import CountryProgramFactory, ProgramFactory  # noqa
from .aurora import ProjectFactory, RegistrationFactory  # noqa
from .smart_fields import DataCheckerFactory, FieldDefinitionFactory, FieldsetFactory, FlexFieldFactory  # noqa
from .social import SocialAuthUserFactory  # noqa
from .sync import SyncLogFactory  # noqa
from .user import GroupFactory, SuperUserFactory, User, UserFactory  # noqa
from .userrole import UserRole, UserRoleFactory  # noqa
from .version import ScriptFactory  # noqa
from .workspaces import CountryChecker  # noqa

for _, name, _ in pkgutil.iter_modules([str(Path(__file__).parent)]):
    importlib.import_module(f".{name}", __package__)


django_model_factories = {factory._meta.model: factory for factory in DjangoModelFactory.__subclasses__()}


def get_factory_for_model(
    _model,
) -> type[TAutoRegisterModelFactory] | type[DjangoModelFactory]:
    class Meta:
        model = _model

    bases = (AutoRegisterModelFactory,)
    if _model in factories_registry:
        return factories_registry[_model]  # noqa

    if _model in django_model_factories:
        return django_model_factories[_model]

    return register(type(f"{_model._meta.model_name}AutoCreatedFactory", bases, {"Meta": Meta}))  # noqa
