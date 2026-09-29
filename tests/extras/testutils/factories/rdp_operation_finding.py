import factory

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.models import RdpOperationFinding

from .base import AutoRegisterModelFactory
from .individual import IndividualFactory
from .rdp_operation import RdpOperationFactory


class RdpOperationFindingFactory(AutoRegisterModelFactory):
    operation = factory.SubFactory(RdpOperationFactory)
    # Use a standalone finding by default; duplicate findings require related_individual.
    finding_type = FindingStatusCode.BAD_IMAGE_QUALITY.name
    individual = factory.SubFactory(IndividualFactory)

    class Meta:
        model = RdpOperationFinding
