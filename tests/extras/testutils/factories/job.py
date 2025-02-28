import factory

from country_workspace.models import AsyncJob

from .base import AutoRegisterModelFactory
from .program import ProgramFactory


class AsyncJobFactory(AutoRegisterModelFactory):
    type = AsyncJob.JobType.FQN
    program = factory.SubFactory(ProgramFactory)
    batch = None
    file = None
    config = {}

    class Meta:
        model = AsyncJob
