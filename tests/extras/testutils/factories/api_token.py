import factory

from country_workspace.api.grants import APIGrant
from country_workspace.models import APIToken

from .base import AutoRegisterModelFactory
from .office import OfficeFactory
from .user import UserFactory


class APITokenFactory(AutoRegisterModelFactory):
    user = factory.SubFactory(UserFactory)
    grants = factory.LazyFunction(lambda: [APIGrant.HOPE_RDI_CALLBACK.value])

    class Meta:
        model = APIToken

    @factory.post_generation
    def valid_for(self, create: bool, extracted, **kwargs) -> None:
        """Handle valid_for office scope."""
        if not create:
            return

        offices = extracted if extracted is not None else [OfficeFactory()]
        if isinstance(offices, (list, tuple, set)):
            self.valid_for.set(offices)
            return

        self.valid_for.add(offices)
