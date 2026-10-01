from django.db.models import BooleanField, Count, Exists, F, IntegerField, OuterRef, Q, QuerySet, Value

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.models import Household, Individual, Program, Rdp, RdpOperation, RdpOperationFinding
from country_workspace.rdp.repository import qs_individuals_for_rdp, rdp_selection

from .constants import BIOMETRIC_AFFECTING_FINDING_TYPES, BIOMETRIC_IMAGE_ISSUE_FINDING_TYPES


def rdp_for_dedup(*, pk: int) -> Rdp:
    """Return RDP with related Program loaded for dedup workflow."""
    return Rdp.objects.select_related("program").get(pk=pk)


def biometric_operation_for_rdp(*, rdp: Rdp) -> RdpOperation | None:
    """Return the biometric deduplication operation for an RDP."""
    return rdp.operations.filter(operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION).first()


def qs_successful_biometric_operations() -> QuerySet[RdpOperation]:
    """Return successful biometric deduplication operations."""
    return RdpOperation.objects.filter(
        operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
        status=RdpOperation.Status.SUCCESS,
    )


def qs_biometric_duplicate_individuals(*, operation: RdpOperation) -> QuerySet[Individual]:
    """Return local individuals marked duplicate by a biometric operation."""
    return Individual.objects.filter(
        Q(
            rdp_operation_findings__operation=operation,
            rdp_operation_findings__finding_type=FindingStatusCode.DUPLICATE.name,
        )
        | Q(
            related_rdp_operation_findings__operation=operation,
            related_rdp_operation_findings__finding_type=FindingStatusCode.DUPLICATE.name,
        )
    ).distinct()


def qs_biometric_affected_individuals(*, operation: RdpOperation) -> QuerySet[Individual]:
    """Return RDP individuals affected by biometric findings."""
    return (
        qs_individuals_for_rdp(rdp=operation.rdp)
        .filter(
            Q(
                rdp_operation_findings__operation=operation,
                rdp_operation_findings__finding_type__in=BIOMETRIC_AFFECTING_FINDING_TYPES,
            )
            | Q(
                related_rdp_operation_findings__operation=operation,
                related_rdp_operation_findings__finding_type__in=BIOMETRIC_AFFECTING_FINDING_TYPES,
            )
        )
        .distinct()
    )


def has_biometric_image_issues(*, operation: RdpOperation) -> bool:
    """Return whether biometric deduplication produced image-related issues."""
    return operation.findings.filter(finding_type__in=BIOMETRIC_IMAGE_ISSUE_FINDING_TYPES).exists()


def biometric_findings_count(*, operation: RdpOperation) -> int:
    """Return the number of biometric findings that would create HOPE tickets."""
    return operation.findings.filter(
        finding_type__in=BIOMETRIC_AFFECTING_FINDING_TYPES,
    ).count()


def biometric_clean_rdp_selection(*, operation: RdpOperation) -> tuple[bool, list[int]]:
    """Return the RDP selection excluding beneficiaries affected by biometric findings."""
    master_detail, pks = rdp_selection(rdp=operation.rdp)
    affected = qs_biometric_affected_individuals(operation=operation)
    excluded = set(affected.values_list("household_id" if master_detail else "pk", flat=True))
    return master_detail, [pk for pk in pks if pk not in excluded]


def _qs_biometric_image_issue_individuals(*, operation: RdpOperation) -> QuerySet[Individual]:
    """Return RDP individuals with biometric image issues."""
    return (
        qs_individuals_for_rdp(rdp=operation.rdp)
        .filter(
            rdp_operation_findings__operation=operation,
            rdp_operation_findings__finding_type__in=BIOMETRIC_IMAGE_ISSUE_FINDING_TYPES,
        )
        .distinct()
    )


def _qs_successful_biometric_duplicate_individuals(*, program: Program) -> QuerySet[Individual]:
    """Return individuals marked duplicate by successful biometric operations."""
    operations = qs_successful_biometric_operations().filter(rdp__program=program)
    return Individual.objects.filter(
        Q(
            rdp_operation_findings__operation__in=operations,
            rdp_operation_findings__finding_type=FindingStatusCode.DUPLICATE.name,
        )
        | Q(
            related_rdp_operation_findings__operation__in=operations,
            related_rdp_operation_findings__finding_type=FindingStatusCode.DUPLICATE.name,
        )
    ).distinct()


def _qs_successful_biometric_image_issue_individuals(*, program: Program) -> QuerySet[Individual]:
    """Return individuals with image issues from successful biometric operations."""
    operations = qs_successful_biometric_operations().filter(rdp__program=program)
    issues = Q(
        rdp_operation_findings__operation__in=operations,
        rdp_operation_findings__finding_type__in=BIOMETRIC_IMAGE_ISSUE_FINDING_TYPES,
    )

    if program.is_master_detail:
        issues &= Q(rdp_operation_findings__operation__rdp__households__pk=F("household_id"))
    else:
        issues &= Q(rdp_operation_findings__operation__rdp__individuals__pk=F("pk"))

    return Individual.objects.filter(issues).distinct()


def biometric_findings_for_individual(
    *,
    individual: Individual,
    rdp: Rdp | None = None,
) -> tuple[list[int], list[str]]:
    """Return duplicate counterparts and image issues for an individual."""
    operations = qs_successful_biometric_operations().filter(rdp__program=individual.program)
    if rdp:
        operations = operations.filter(rdp=rdp)

    findings = RdpOperationFinding.objects.filter(operation__in=operations)

    duplicate_pks: set[int] = set()
    for first_id, second_id in (
        findings.filter(finding_type=FindingStatusCode.DUPLICATE.name)
        .filter(Q(individual=individual) | Q(related_individual=individual))
        .values_list("individual_id", "related_individual_id")
    ):
        if (counterpart_id := second_id if first_id == individual.pk else first_id) is not None:
            duplicate_pks.add(counterpart_id)

    image_issues = list(
        findings.filter(
            individual=individual,
            finding_type__in=BIOMETRIC_IMAGE_ISSUE_FINDING_TYPES,
        )
        .values_list("finding_type", flat=True)
        .distinct()
        .order_by("finding_type")
    )
    return sorted(duplicate_pks), image_issues


def annotate_biometric_households(
    qs: QuerySet[Household],
    *,
    program: Program,
    rdp: Rdp | None,
) -> QuerySet[Household]:
    """Annotate households with biometric result counts."""
    if rdp:
        operation = biometric_operation_for_rdp(rdp=rdp)
        duplicates = qs_biometric_duplicate_individuals(operation=operation) if operation else Individual.objects.none()
        image_issues = (
            _qs_biometric_image_issue_individuals(operation=operation) if operation else Individual.objects.none()
        )
        actual_members = Q()
        result_available = Value(
            operation is not None and operation.status == RdpOperation.Status.SUCCESS,
            output_field=BooleanField(),
        )
    else:
        duplicates = _qs_successful_biometric_duplicate_individuals(program=program)
        image_issues = _qs_successful_biometric_image_issue_individuals(program=program)
        actual_members = Q(members__removed=False)
        result_available = Exists(
            qs_successful_biometric_operations().filter(
                rdp__program=program,
                rdp__households__pk=OuterRef("pk"),
            )
        ) | Exists(
            duplicates.filter(
                household_id=OuterRef("pk"),
                removed=False,
            )
        )

    return qs.annotate(
        _member_count=Count("members", filter=actual_members, distinct=True),
        _duplicate_member_count=Count("members", filter=actual_members & Q(members__in=duplicates), distinct=True),
        _image_issue_member_count=Count("members", filter=actual_members & Q(members__in=image_issues), distinct=True),
        _result_available=result_available,
        _selected_rdp_id=Value(rdp.pk if rdp else None, output_field=IntegerField()),
    )


def annotate_biometric_individuals(
    qs: QuerySet[Individual],
    *,
    program: Program,
    rdp: Rdp | None,
) -> QuerySet[Individual]:
    """Annotate individuals with biometric result state."""
    if rdp:
        operation = biometric_operation_for_rdp(rdp=rdp)
        duplicates = qs_biometric_duplicate_individuals(operation=operation) if operation else Individual.objects.none()
        image_issues = (
            _qs_biometric_image_issue_individuals(operation=operation) if operation else Individual.objects.none()
        )
        result_available = Value(
            operation is not None and operation.status == RdpOperation.Status.SUCCESS,
            output_field=BooleanField(),
        )
    else:
        duplicates = _qs_successful_biometric_duplicate_individuals(program=program)
        image_issues = _qs_successful_biometric_image_issue_individuals(program=program)
        operations = qs_successful_biometric_operations().filter(rdp__program=program)
        membership = (
            Q(rdp__households__pk=OuterRef("household_id"))
            if program.is_master_detail
            else Q(rdp__individuals__pk=OuterRef("pk"))
        )
        result_available = Exists(operations.filter(membership)) | Exists(duplicates.filter(pk=OuterRef("pk")))

    return qs.annotate(
        _is_duplicate=Exists(duplicates.filter(pk=OuterRef("pk"))),
        _has_image_issue=Exists(image_issues.filter(pk=OuterRef("pk"))),
        _result_available=result_available,
    )
