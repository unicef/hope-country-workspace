import factory

from .base import AutoRegisterModelFactory
from .program import ProgramFactory
from country_workspace.models import AsyncJob


class AsyncJobFactory(AutoRegisterModelFactory):
    type = AsyncJob.JobType.FQN
    program = factory.SubFactory(ProgramFactory)
    batch = None
    file = None
    config = {}

    class Meta:
        model = AsyncJob
