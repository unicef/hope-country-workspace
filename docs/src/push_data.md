### Prerequisites

Before pushing data to the HOPE core system, you must [validate](#validation.md) households along with their members.

---

### Processing

##### Navigate to Households
In the [Collector Interface](interfaces.md#collector-interface), navigate to the menu
```
Households
```
!!! warning
    Only beneficiaries not marked as removed are displayed in this interface.

##### Select and Initiate Push

Select the relevant households, choose the **Push to HOPE core** action, and click **[Go]**. This opens a form where you can set the batch options.


##### Configure Batch Options
In the form, you can adjust:

- **Batch Name** – A label for the RDI-to-HOPE batch. This parameter is optional; if omitted, the default value is *"RDI to HOPE " + the current datetime*.

##### Start the Process
Click **[Push]** to start the process. You will be redirected to the **Jobs** page to monitor the job's progress and details.

##### Post-Push Status
After a successful push, all households and their members that were sent will be marked as **removed**. To review removed beneficiaries, use the [Admin Interface](interfaces.md#admin-interface).

---

### External collectors

[External collectors](data_import/sources/kobo.md#external-collectors) are not household members. When a selected Household references one as Primary or Alternate Collector, Country Workspace includes that collector in the push. If several selected Households reference the same collector, the collector is sent only once in that push.

They are also not marked as **removed** after a push, because households that have not been pushed yet may still reference them.

!!! note
    If the referencing Households are pushed in separate batches, Country Workspace includes the collector in each batch. HOPE-side handling of these repeated submissions depends on HOPE's RDI and deduplication behavior.

    Push all referencing Households in the same batch when Country Workspace should submit only one copy of the shared collector.
