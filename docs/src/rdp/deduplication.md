# RDP deduplication

For Programs with biometric deduplication enabled, Country Workspace uses beneficiary photos from an **[RDP](index.md)** to run biometric deduplication in DedupEngine.

Deduplication uses the current settings configured for the selected **[Program](../program.md#deduplication-settings)**.

## When deduplication is available

The **Deduplicate** button is shown for biometric RDPs in `PENDING` or `FAILURE` status.

The button is enabled when:

- no other deduplication run is already queued or running;
- DedupEngine allows a new Deduplication Set to be created, or the existing set is in `Ready` state.

Otherwise, the **Deduplicate** button is disabled.

## Run deduplication

Open the RDP and click **Deduplicate**.

Country Workspace schedules a background job to start processing in DedupEngine.

For a new Deduplication Set, Country Workspace creates the set, uploads the available beneficiary photos, marks the set as ready, and starts processing. If the RDP already has a set in `Ready` state, that set is processed instead.

Running deduplication does not change the RDP status. An RDP in `PENDING` remains `PENDING`, and an RDP in `FAILURE` remains `FAILURE`.

## Dedup engine state

For open biometric RDPs, **Dedup engine state** shows the current state of the associated Deduplication Set.

This is independent of the RDP **Status**. For example, a failed push can leave the RDP in `FAILURE` while its Deduplication Set remains `Deduplicated`.

When available, the number of findings is displayed together with the state, for example:

`Encoding in progress / 0 findings`

Common displayed values include:

| Displayed value | Meaning |
| --- | --- |
| `Ready to start` | A new Deduplication Set can be created. |
| `Ready` | The existing set is ready to be processed. |
| `Uploading in progress` | Biometric data is being uploaded. |
| `Encoding in progress` | DedupEngine is encoding the uploaded images. |
| `Encoded` | Encoding has completed. |
| `Deduplication in progress` | Deduplication is running. |
| `Deduplicated` | Deduplication has completed and the RDP can proceed to push. |
| `Encoding failed` | Encoding failed in DedupEngine. |
| `Deduplication failed` | Deduplication failed in DedupEngine. |
| `N/A` | The current state could not be retrieved from DedupEngine. |

Other values may be displayed depending on the current Country Workspace and DedupEngine state.

## Related jobs and Operation log

**Related jobs** shows the Country Workspace background jobs associated with the RDP and their execution status. A successful deduplication job means that Country Workspace started processing successfully; DedupEngine may still be processing the set.

**Operation log** records RDP operations. A **Start deduplication** entry includes the time of the run, the number of images sent, the deduplication settings used, and the Deduplication Set ID.

## After deduplication

Once the associated Deduplication Set reaches `Deduplicated`, the RDP can proceed to **[Push to HOPE Core](push.md)**.

For RDP status changes, see **[Lifecycle and statuses](lifecycle.md)**.
