# Troubleshooting

Use the RDP **Operations** and **Processing history** sections to identify where processing stopped.

For the normal workflow, see **[RDP processing flow](processing.md)** and **[Lifecycle and statuses](lifecycle.md)**.

## Common problems

| Problem | What to check |
| --- | --- |
| RDP creation failed | Open the failed **Create RDP** job in **Processing history** and check the preflight error. See **[Create an RDP](create.md)**. |
| RDP remains `PENDING` | Check **Operations** first. If an operation failed, use **Retry failed operations**. If all operations are `SUCCESS`, check **Processing history** for the push evaluation. |
| RDP is `REVIEW_PENDING` | This is not a processing failure. Review is required before continuing. See **[Manual review](operations/deduplication.md#manual-review)**. |
| RDP is `FAILURE` | The HOPE push failed. Check **Processing history**, then use **Retry push to HOPE** when the cause is resolved. |
| **Cancel RDP** is unavailable | **Cancel RDP** is available only for `PENDING`, `REVIEW_PENDING`, or `FAILURE`, and is blocked while an operation is `RUNNING`. See **[Cancel an RDP](lifecycle.md#cancel-an-rdp)**. |

## Operation failed

An operation failure does not change the RDP to `FAILURE`; the RDP remains `PENDING`.

Check the operation error and log in the **Operations** section, then use **Retry failed operations**. The same operation is retried with its existing configuration.

See **[RDP operations](operations/index.md#operation-statuses)** for the common operation lifecycle and **[Biometric deduplication](operations/deduplication.md#failed-biometric-operation)** for biometric failures.

## Push evaluation failed

If all configured operations are `SUCCESS` but the RDP remains `PENDING`, check **Processing history** for a failed **Evaluate RDP for push** job.

Authorized users can open the failed job and use **Queue** to run the push evaluation again.

See **[Operation results and review](processing.md#operation-results-and-review)** for where push evaluation fits into the normal flow.

## RDP remains in `PUSH_PENDING`

`PUSH_PENDING` can be normal while Country Workspace prepares HOPE Core, waits for an RDI reset callback, or transfers beneficiary data.

Check **Processing history** before treating the push as stuck.

If the push can no longer continue, authorized staff can use **Fail stuck push** after confirming that the push preparation job is no longer running and that no HOPE callback is still expected.

See **[Recover a stuck push](lifecycle.md#recover-a-stuck-push)** for the recovery conditions and next steps.

## Push failed

A failed push changes the RDP to `FAILURE`.

Check **Processing history** for the failed preparation or data-push job. If HOPE reports that a previous RDI merge is still in progress, retry after that merge completes.

Use **Retry push to HOPE** to start a new push attempt. See **[Retry a failed push](push.md#retry-a-failed-push)**.

## DedupEngine approval failed after a successful push

For biometric RDPs, Country Workspace attempts to approve the Deduplication Set after the HOPE push succeeds.

An approval failure does not change the RDP from `SUCCESS`; the beneficiary data has already been pushed successfully. Do not retry the HOPE push for this reason alone.

See **[After a successful push](push.md#after-a-successful-push)**.
