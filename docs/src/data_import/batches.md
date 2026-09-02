# Batches

A Batch represents one **[data import](index.md)** within the selected Office and **[Program](../program.md)**. It groups any beneficiary records created by the import and records its source, the user who started it, its date, and processing status.

Batches are created automatically during imports from **[RDI](sources/xlsx.md)**, **[Aurora](sources/aurora.md)**, and **[Kobo](sources/kobo.md)**. They cannot be created manually.

## Open and review a Batch

Open **Batches** in the **[Analyst / Collector Workspace](../interfaces.md#analyst--collector-workspace)** after selecting the required Office and Program.

Only Batches belonging to the selected Office and Program are available.

Open a Batch to review its name, import date, importer, source, status, related jobs, and imported beneficiary records. Each field includes a short description.

Related jobs include import, validation, reprocessing, and picture import tasks associated with the Batch.

For a household-based Program, the Batch provides separate links to its Households and Individuals. For a people-only Program, it provides a link to its People records. The link names follow the beneficiary labels configured for the **[Program](../program.md)**.

### Batch status

A Batch can have one of the following statuses:

| Status       | Meaning                                                                                      |
| ------------ | -------------------------------------------------------------------------------------------- |
| **Loading**  | The import has started but has not completed its final processing.                           |
| **Complete** | The source-specific import process has completed. |

Validation may continue in background jobs after a Batch becomes **Complete**. Validation results can therefore become available after the import itself has finished.

A Batch can remain in **Loading** when an import fails before final processing or while a source-specific continuation job is running. See the corresponding page under **[Data sources](sources/index.md)** for source-specific behavior.

Available actions depend on the user's permissions.

## Reprocessing

Reprocessing applies the current Program processing configuration to records already stored in a Batch.

It uses the source data saved with the imported records and does not request or upload the original source again. Changes made in Aurora, Kobo, or the original Excel workbook after the import are therefore not retrieved during reprocessing.

Use reprocessing to:

* apply a new or updated **[Mapping Importer](mapping_transformers.md#mapping-importers)**;
* apply a new or updated **[Transformer](mapping_transformers.md#transformers)**;
* reapply current Program defaults and source-specific processing rules;
* refresh supported Household role and collector references;
* validate the resulting records again.

Records that have already been pushed to HOPE are excluded from reprocessing.

Pictures added through **[Import pictures](picture_import.md)** are not preserved during reprocessing and must be imported again afterward.

### Configure reprocessing

Open the required Batch, open **Batch actions**, and select **Reprocess Batch**. Select any optional Mapping Importers or Transformers, then select **Confirm**.

For a household-based Program, separate options are available for Households and Individuals.

For a people-only Program, the Individual Mapping Importer and Transformer options are applied to People records.

Available Mapping Importers depend on the corresponding Program **[DataChecker](../data_validation/datachecker_configuration.md#datachecker)**. Available Transformers are limited to the Batch's Office.

Reprocessing can also be started without selecting a Mapping Importer or Transformer. In this case, Country Workspace reapplies the source-specific processing and **[validation configuration](../program.md#validation-configuration)** without additional mapping or transformation.

### How records are reprocessed

```mermaid
flowchart LR
    A[Read stored source data]
        --> B[Apply import processing and mappings]
        --> C[Refresh supported references]
        --> D[Apply Transformers]
        --> E[Schedule validation]
```

**Read stored source data** uses the data saved with each record included in reprocessing.

**Apply import processing and mappings** rebuilds beneficiary fields using the rules for the Batch source, current Program defaults, ignored fields, and any selected Mapping Importer.

**Refresh supported references** updates the Household role references and cross-record collector links supported for the Batch source. Existing Household membership is retained.

**Apply Transformers** applies any selected Household or Individual Transformer after the beneficiary fields have been rebuilt.

**Schedule validation** creates background validation jobs for the reprocessed records.

Reprocessing runs as a background job. Review the reprocessing job to confirm whether the Batch was processed successfully. Validation results become available as the separately scheduled validation jobs finish.

## Import pictures

Pictures can be added to Individuals or People in an existing Batch by uploading a ZIP archive.

See **[Import pictures](picture_import.md)** for matching rules, archive preparation, preview, and confirmation.

## Remove a Batch

A Batch cannot be deleted from the **[Analyst / Collector Workspace](../interfaces.md#analyst--collector-workspace)**.

Staff users can permanently remove a Batch from **[Staff Administration](../interfaces.md#staff-administration)** by opening the Batch and using the **Batch cleanup** action.

Batch cleanup runs as a background job and deletes:

* the Batch;
* its related Households;
* its related Individuals or People.

This operation cannot be undone.

## Troubleshooting

Review the relevant background job when Batch processing does not complete as expected.

Most Batch problems relate to import or reprocessing: the import did not complete, stored source data is missing, the selected processing configuration is incompatible, or some records were already pushed to HOPE and excluded.

For picture import issues, see **[Import pictures](picture_import.md#troubleshooting)**.

For source-specific import problems, see **[Data sources](sources/index.md)**.

For general import issues, see **[Troubleshooting](troubleshooting.md)**.
