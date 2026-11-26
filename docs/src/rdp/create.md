# Create an RDP

A **Registration Data Push (RDP)** contains beneficiary records selected for processing and transfer to HOPE Core.

RDPs are created within the selected **[Program](../program.md)** in the **[Analyst / Collector Workspace](../interfaces.md#analyst-collector-workspace)**.

## Before creating an RDP

Make sure that the required **Office** and **Program** are selected and that the beneficiary records are ready for RDP processing.

Country Workspace validates the records required for the RDP. Creation is blocked if no beneficiaries are selected, required records are invalid or conflict with an open or successful RDP, or another unfinished RDP already exists for the Program.

For household-based Programs, validation also covers the Individuals required for the push, including referenced collectors.

## Configure RDP processing

Select the beneficiary records and choose **Create RDP**.

The optional **Batch name** becomes the RDP name. If it is left blank, Country Workspace generates a name in the form `RDP YYYY-MM-DD HH:MM:SS`.

The creation page shows only the **[RDP operations](operations/index.md)** enabled for the [Program](../program.md). All available operations are selected by default.

- **[OCR](operations/ocr.md)** and **[biographic deduplication](operations/biographic-deduplication.md)** can be deselected for the RDP without changing the Program configuration.
- **[Biometric deduplication](operations/biometric-deduplication.md)** is mandatory when enabled by HOPE and cannot be deselected.

If no operations are available, the Operations section is not displayed. If biometric deduplication is not enabled, the RDP can be created without any operations.

Each selected operation has its own review threshold, configured as **Max number of findings** or **Max findings rate (%)**. The rate calculation depends on the operation. Threshold inputs are disabled for deselected operations.

See the operation-specific pages for threshold details and **[Review and Clean RDP](review.md)** for how thresholds affect the workflow.

## Create the RDP

After the configuration is submitted, Country Workspace schedules RDP creation. The background job validates the beneficiary selection and checks that the selected CW-managed operations are still enabled for the Program before saving the RDP.

```mermaid
flowchart LR
    A[Select beneficiaries]
        --> B[Configure RDP and operations]
        --> C[Schedule creation]
        --> D{Creation checks pass?}
    D -->|No| E[Creation fails]
    D -->|Yes| F[Create RDP<br/>PENDING]
    F --> G{Any operations selected?}
    G -->|Yes| H[Start RDP operations]
    G -->|No| I[Evaluate RDP for push]
```

If the checks succeed, Country Workspace creates the RDP in `PENDING`, links the selected beneficiaries, creates only the selected operations, and starts processing automatically.

If a check fails, the RDP is not created and the failure is recorded in the background job.

## After creation

Configured operations run independently while the RDP remains `PENDING`.

After all configured operations complete successfully, Country Workspace evaluates their review thresholds. The RDP then either continues automatically toward the **[HOPE Core push](push.md)** or moves to `REVIEW_PENDING`.

An RDP without operations proceeds directly to push evaluation and continues automatically toward the HOPE Core push without manual review. The usual push preflight checks still apply.

See **[RDP operations](operations/index.md)** for operation processing, **[Review and Clean RDP](review.md)** for manual review, and **[Lifecycle and statuses](lifecycle.md)** for the complete state flow.
