# Troubleshooting

Use the RDP **Operations** and **Processing history** sections to identify where processing stopped.

For the normal workflow, see **[RDP processing flow](processing.md)** and **[Lifecycle and statuses](lifecycle.md)**.

## Common problems

| Problem | What to check |
| --- | --- |
| RDP creation failed | Open the failed **Create RDP** job in **Processing history** and check the error. See **[Create an RDP](create.md)**. |
| RDP remains `PENDING` | Check **Operations** first. Recover an available operation with **Retry operations**; if all operations are `SUCCESS`, check the push-evaluation job in **Processing history**. |
| Clean replacement RDP remains `PENDING` | With biometric deduplication, replacement operations start only after the source Deduplication Set is rejected. Check the source RDP's **Processing history**. See **[Replacement RDP](review.md#replacement-rdp)**. |
| RDP is `REVIEW_PENDING` | This is not a processing failure. See **[Review and Clean RDP](review.md)**. |
| RDP is `FAILURE` | The push attempt failed. Check **Processing history**, resolve the cause, then use **Retry push to HOPE**. |
| RDP remains `PUSH_PENDING` | Check whether Country Workspace is still waiting for HOPE or transferring data before treating the push as stuck. |
| **Cancel RDP** is unavailable or fails | It is available only for `PENDING`, `REVIEW_PENDING`, or `FAILURE` RDPs and is blocked while an operation is `RUNNING`. For biometric RDPs, cancellation also requires a Deduplication Set state that can be safely verified and handled. See **[Cancel an RDP](lifecycle.md#cancel-an-rdp)**. |

## Operation requires recovery

A technical operation failure leaves the RDP in `PENDING`; it does not change the RDP itself to `FAILURE`.

Check the operation status, error, and execution log in **Operations**. Use **Retry operations** for failed operations or for another operation state that explicitly supports manual recovery.

For OCR, a `RUNNING` attempt can also be restarted when its current result is no longer expected. Completed OCR work is preserved and stale results from the previous attempt are ignored. A `RUNNING` biometric operation should not be restarted because DedupEngine may still be processing it.

See **[RDP operations](operations/index.md#operation-statuses)**, **[OCR recovery](operations/ocr.md#recovery)**, and **[Failed biometric operation](operations/deduplication.md#failed-biometric-operation)**.

## Push evaluation failed

After all configured operations reach `SUCCESS`, Country Workspace runs **Evaluate RDP for push** to determine whether review is required or the push can start.

If that job fails, the RDP remains `PENDING`. Open the failed job in **Processing history** and use **Queue** to run the repeatable evaluation again after the cause has been resolved.

See **[Findings and review](processing.md#findings-and-review)** for where evaluation fits into the normal flow.

## RDP remains in `PUSH_PENDING`

`PUSH_PENDING` can be normal while Country Workspace prepares HOPE Core, waits for an RDI reset callback, or transfers beneficiary data.

Check **Processing history** before treating the push as stuck.

If the push can no longer continue, authorized staff can use **Fail stuck push** after confirming that the push preparation job is no longer running and that no HOPE callback is still expected. Successful recovery changes the RDP to `FAILURE`.

See **[Recover a stuck push](lifecycle.md#recover-a-stuck-push)** for the recovery conditions and **[Retry a failed push](push.md#retry-a-failed-push)** for the next step.

## Push failed

A failed push attempt changes the RDP to `FAILURE`.

Check **Processing history** for the push preparation and data-push steps. Failures can occur during HOPE preparation, callback handoff, preflight validation, or data transfer. If HOPE reports that a previous RDI merge is still in progress, retry only after that merge completes.

Use **Retry push to HOPE** to start a new push attempt. See **[Push to HOPE Core](push.md)** for the complete push workflow.

## DedupEngine approval failed after a successful push

For biometric RDPs, Country Workspace attempts to approve the Deduplication Set after the HOPE push succeeds.

An approval failure does not change the RDP from `SUCCESS`; the beneficiary data has already been pushed successfully. Do not retry the HOPE push for this reason alone.

See **[Deduplication Set lifecycle](operations/deduplication.md#deduplication-set-lifecycle)**.
