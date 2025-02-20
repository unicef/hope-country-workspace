# Data cleaning and updates.

There are several options to clean data for households or individuals in the collector interface.

## Bulk Actions

The system allows users to perform mass operations on multiple records at once. These actions help streamline data management by applying updates to multiple `Household` or `Individual` entities in a single process.

### In-System Bulk Data Modifications

To perform bulk updates, go to:
```
Home › Households | Individuals
```
Select the records and apply the desired action:

- **Mass update record fields**

    Allows the user to define values and apply them using functions like:

    ```
    set, set null, upper, lower, toggle, ...
    ```

- **Update fields using RegEx**

    Allows the user to define a regular expression and a substitution pattern for any field and apply it.

---

### Bulk Data Export, Offline Editing, and Reimport

Users can modify data in bulk by exporting records to a `.xlsx` file, making necessary changes outside the system, and then importing the updated file back.

The `.xlsx` file contains two protected columns: `id` and `version`. **These columns should not be modified during regular editing**, as they are essential for correctly identifying and updating records.

Additionally, the system includes a **concurrency control mechanism** to prevent accidental overwrites of updated data.

#### Process Overview

1. **Export Data**

    To begin, navigate to:
    ```
    Home › Households | Individuals
    ```
    Select the records and apply the action **"Export records as .xlsx for bulk updates"**.
    Then, choose the columns to update and press **[Export]**.
    The export process will be scheduled as an asynchronous task.

2. **Edit the Exported File**

    Once the `.xlsx` file is generated, update the necessary values while ensuring that the `id` and `version` columns remain unchanged.

3. **Import the Updated File Back into the System**

    After making the necessary modifications, navigate to:
    ```
    Home › Program
    ```
    Press **[Update Records]**, select the file, choose the target (`Household | Individual`), and optionally provide a description.
    Finally, press **[Import]**. This action will schedule an asynchronous task to process the updates.

#### **Preventing Conflicts with `CONCURRENCY_GUARD`**

To ensure data consistency, the system provides the **`CONCURRENCY_GUARD`** parameter.
When enabled, it prevents updates if a record has changed after the export. This ensures that newer modifications made by other users or processes are not accidentally overwritten during import.
If a conflict is detected, the system will reject the update, requiring the user to re-export the latest data before making further changes.

---

## **Single-Entity Operations**

Unlike bulk actions, these operations apply to a single `Household` or `Individual` entry. To access these actions, go to:
```
Home › Households | Individuals
```
Select a specific `Household` or `Individual`, then use the available buttons:

### Validate
Ensures that the record meets the required data standards.
If any issues are detected, the affected fields turn red, and an explanatory error message appears.

### View Raw Data

Allows the user to see the raw, unprocessed data of the selected record.
This can be useful for debugging or reviewing the exact stored values before applying further modifications.
