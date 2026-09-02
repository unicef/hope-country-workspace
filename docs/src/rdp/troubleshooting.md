# Troubleshooting

This page covers common problems that can occur while creating, deduplicating, pushing, or cancelling an **[RDP](index.md)**.

## What to check first

When an RDP does not proceed as expected, check **Status**, **Dedup engine state** for biometric RDPs, **Related jobs**, and **Operation log**.

See **[Statuses](lifecycle.md#statuses)** and **[Processing sequence](processing.md#processing-sequence)** for the overall workflow.

## RDP cannot be created

Creation can be blocked when:

- no beneficiaries are selected;
- beneficiary records included in the RDP are invalid;
- selected records are already linked to an unfinished or successful RDP;
- another unfinished RDP already exists for the Program;
- for a biometric Program, DedupEngine does not allow a new Deduplication Set.

Review the displayed error and resolve the blocking condition.

See **[Before creating an RDP](create.md#before-creating-an-rdp)**.

## Deduplicate button is unavailable

The **Deduplicate** button is available only for biometric RDPs in `PENDING` or `FAILURE`.

It is disabled while another deduplication operation is queued or running, or when DedupEngine does not allow processing to start. An existing Deduplication Set can be processed only in `Ready` state.

See **[When deduplication is available](deduplication.md#when-deduplication-is-available)**.

## Deduplication does not complete

Check **Related jobs** for Country Workspace processing and **Dedup engine state** for processing in DedupEngine.

A completed Country Workspace job does not mean that DedupEngine has finished processing the set.

If the state is `Encoding failed` or `Deduplication failed`, the existing set cannot be processed again from Country Workspace while it remains in that state.

If the state is `N/A`, check again after DedupEngine becomes available.

See **[Dedup engine state](deduplication.md#dedup-engine-state)**.

## Push to HOPE button is unavailable

The **Push to HOPE** button is available only for RDPs in `PENDING` or `FAILURE`.

The push cannot start while deduplication is queued or running. For biometric RDPs, the associated Deduplication Set must be `Deduplicated`.

See **[When push is available](push.md#when-push-is-available)**.

## Push failed

A failed push changes the RDP to `FAILURE`.

Check **Related jobs** for the failure reason. Preflight checks are repeated before data is sent, so changes to the RDP records after creation can also cause the push to fail.

If a retry requires resetting a previous HOPE RDI, Country Workspace performs the reset as part of the retry. A retry fails while HOPE reports that the previous RDI merge is still in progress.

See **[Retry a failed push](push.md#retry-a-failed-push)**.

## RDP remains in `PUSH_PENDING`

`PUSH_PENDING` means that a push attempt is still active. The RDP can remain in this state while the push is being prepared, while Country Workspace is waiting for HOPE after an RDI reset, or while data is being transferred.

Check **Related jobs** before treating the push as stuck. If the expected HOPE response will no longer arrive, recovery by authorized staff may be required before the push can be retried.

## Cancel button is unavailable

The **Cancel** button is available only for RDPs in `PENDING` or `FAILURE` and is disabled while deduplication is queued or running.

See **[Cancel an RDP](lifecycle.md#cancel-an-rdp)**.

## RDP is `SUCCESS` but DedupEngine approval failed

For biometric RDPs, DedupEngine approval happens after a successful push. An approval failure does not change the RDP from `SUCCESS`.

Check the **Operation log** for the approval result. The HOPE push should not be retried because of an approval failure alone.

See **[After a successful push](push.md#after-a-successful-push)**.
