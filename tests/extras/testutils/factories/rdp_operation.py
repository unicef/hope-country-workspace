import factory

from country_workspace.models import RdpOperation
from country_workspace.rdp.deduplication.types import ThresholdType

from .base import AutoRegisterModelFactory
from .rdp import RdpFactory


class RdpOperationFactory(AutoRegisterModelFactory):
    rdp = factory.SubFactory(RdpFactory)
    operation_type = RdpOperation.Type.BIOMETRIC_DEDUPLICATION
    config = factory.LazyFunction(
        lambda: {
            "threshold_type": ThresholdType.COUNT.value,
            "threshold_value": "0",
        }
    )

    class Meta:
        model = RdpOperation
