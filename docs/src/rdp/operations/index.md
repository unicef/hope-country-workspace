# RDP operations

RDP operations are processing steps that can run after an **[RDP](../index.md)** is created and before it is pushed to HOPE Core.

Operations run independently and keep their own configuration, status, attempts, findings, and errors. The RDP remains `PENDING` until all configured operations complete successfully.

## Supported operations

| Operation | Availability | Purpose |
| --- | --- | --- |
| **[OCR](ocr.md)** | Enabled by default; configurable in Country Workspace | Checks identity-document images against the expected document number. |
| **[Biometric deduplication](biometric-deduplication.md)** | Controlled by HOPE; mandatory when enabled | Checks beneficiary photos for duplicates and image-quality problems. |
| **[Biographic deduplication](biographic-deduplication.md)** | Enabled by default; configurable in Country Workspace | Checks beneficiary names, birth dates and phone numbers for duplicate people. |

## Configuration

Operation availability is defined in the **[Program configuration](../../program.md#rdp-operations)**.

During **[RDP creation](../create.md#configure-rdp-processing)**, Country Workspace shows only the enabled operations, all selected by default. OCR and biographic deduplication can be deselected for the RDP; biometric deduplication cannot be deselected when enabled. Only selected operations are created and run.

Each operation stores its own settings. These settings are reused when the operation is retried and are also used to determine whether its findings require **[manual review](../review.md)**.

OCR and both deduplication operations support **Max number of findings** and **Max findings rate (%)** thresholds. Manual review is required only when the configured maximum is exceeded. The count and rate calculations are operation-specific; see the corresponding operation page for details. The default is **Max number of findings = 0**, so any finding requires manual review unless the threshold is changed.

## Processing

Each configured operation starts in `PENDING` and is processed independently.

```mermaid
flowchart LR
    A[PENDING] --> B[RUNNING]
    B -->|Completed| C[SUCCESS]
    B -->|Technical failure| D[FAILURE]
    D -->|Retry operations| B
```

A technical failure changes the operation to `FAILURE`. Business findings do not: an operation can complete with `SUCCESS` and still produce findings that require review.

Country Workspace continues the RDP workflow only after all configured operations are `SUCCESS`. If the RDP has no operations, it proceeds directly to push evaluation.

See **[RDP processing flow](../processing.md)** for the complete end-to-end workflow.

## Operation statuses

| Status | Meaning |
| --- | --- |
| `PENDING` | Waiting to start or to continue after recovery. |
| `RUNNING` | Processing is in progress. |
| `SUCCESS` | Processing completed successfully, with or without findings. |
| `FAILURE` | Processing failed and requires recovery. |

Use **Retry operations** for failed or otherwise recoverable operations. Failed operations are retried first; if none have failed, a `RUNNING` operation that supports manual recovery can be restarted. Operation-specific completed work is preserved where supported.

See **[OCR](ocr.md#recovery)**, **[Biometric deduplication](biometric-deduplication.md#failed-biometric-operation)** and **[Biographic deduplication](biographic-deduplication.md#failed-biographic-operation)** for operation-specific behavior.

## Findings and review

OCR, biometric and biographic deduplication store their adverse business results as operation findings.

After all configured operations complete successfully, Country Workspace evaluates each operation threshold independently. If any threshold is exceeded, the RDP moves to `REVIEW_PENDING`; otherwise it continues automatically to the **[HOPE Core push](../push.md)**.

The workspace provides a shared Findings view with filtering and pagination. Findings are also summarized on relevant Individual and Household pages. When an RDP is opened explicitly, the summaries show findings from that RDP; normal Program-wide views show the latest relevant findings by operation type.

See **[Review and Clean RDP](../review.md)** for review decisions and **[OCR](ocr.md#findings)**, **[Biometric deduplication](biometric-deduplication.md#findings)** or **[Biographic deduplication](biographic-deduplication.md#findings)** for operation-specific findings.

## Operation details

The RDP page contains an **Operations** section when at least one operation is configured.

It shows the operation type and identifier, status, timing, number of attempts, configuration, last error, execution log, saved finding count, and affected Individual count where applicable.

Use the finding count to open the detailed Findings view for that operation.
