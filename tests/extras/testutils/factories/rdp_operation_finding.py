import factory

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.models import RdpOperationFinding

from .base import AutoRegisterModelFactory
from .individual import IndividualFactory
from .rdp_operation import BiometricRdpOperationFactory


class RdpOperationFindingFactory(AutoRegisterModelFactory):
    individual = factory.SubFactory(IndividualFactory)

    class Meta:
        model = RdpOperationFinding
        abstract = True


class BiometricRdpOperationFindingFactory(RdpOperationFindingFactory):
    operation = factory.SubFactory(BiometricRdpOperationFactory)
    # Use a standalone finding by default; duplicate findings require related_individual.
    finding_type = FindingStatusCode.BAD_IMAGE_QUALITY.name
