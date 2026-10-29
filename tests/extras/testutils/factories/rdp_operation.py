import factory

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.contrib.hope.constants import DOCUMENT_TYPES
from country_workspace.models import RdpOperation, RdpOperationFinding, RdpOperationUnit
from country_workspace.rdp.ocr.types import OcrFindingType
from country_workspace.rdp.types import ThresholdType

from .base import AutoRegisterModelFactory
from .individual import IndividualFactory
from .rdp import RdpFactory


class RdpOperationFactory(AutoRegisterModelFactory):
    rdp = factory.SubFactory(RdpFactory)

    class Meta:
        model = RdpOperation
        abstract = True


class BiometricRdpOperationFactory(RdpOperationFactory):
    operation_type = RdpOperation.Type.BIOMETRIC_DEDUPLICATION
    config = factory.LazyFunction(
        lambda: {
            "threshold_type": ThresholdType.COUNT.value,
            "threshold_value": "0",
        }
    )


class OcrRdpOperationFactory(RdpOperationFactory):
    operation_type = RdpOperation.Type.OCR
    config = factory.LazyFunction(
        lambda: {
            "threshold_type": ThresholdType.COUNT.value,
            "threshold_value": "0",
        }
    )


class RdpOperationFindingFactory(AutoRegisterModelFactory):
    individual = factory.SubFactory(IndividualFactory)

    class Meta:
        model = RdpOperationFinding
        abstract = True


class BiometricRdpOperationFindingFactory(RdpOperationFindingFactory):
    operation = factory.SubFactory(BiometricRdpOperationFactory)
    finding_type = FindingStatusCode.BAD_IMAGE_QUALITY.name


class OcrRdpOperationFindingFactory(RdpOperationFindingFactory):
    operation = factory.SubFactory(OcrRdpOperationFactory)
    finding_type = OcrFindingType.NO_MATCH.value
    details = factory.LazyFunction(lambda: {"document_type": DOCUMENT_TYPES[0]})


class RdpOperationUnitFactory(AutoRegisterModelFactory):
    class Meta:
        model = RdpOperationUnit
        abstract = True


class OcrRdpOperationUnitFactory(RdpOperationUnitFactory):
    operation = factory.SubFactory(OcrRdpOperationFactory)
    individual = factory.LazyAttribute(
        lambda obj: IndividualFactory(
            household=None,
            batch__program=obj.operation.rdp.program,
        )
    )
    config = factory.LazyFunction(lambda: {"document_type": DOCUMENT_TYPES[0]})
