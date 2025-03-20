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
