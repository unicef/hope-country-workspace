# RDI (Excel file)

RDI imports beneficiary data from an Excel workbook into the selected **[Program](../../program.md)**.

The required workbook structure depends on the Program's **[Beneficiary Group](../../program.md#beneficiary-structure)**, while the expected columns, value types, and validation rules depend on its **[DataCheckers](../../data_validation/datachecker_configuration.md)**.

## Prepare the workbook

### Workbook structure

For a household-based Program, the workbook must contain sheets named exactly `Households` and `Individuals`. For a people-only Program, it must contain a sheet named exactly `People`.

### Columns and values

Workbook columns represent beneficiary fields configured in the Program's [DataCheckers](../../data_validation/datachecker_configuration.md).

Column names, value types, required fields, and validation rules depend on the corresponding Program DataCheckers. Use a **[Mapping Importer](../mapping_transformers.md#mapping-importers)** when source column names differ from the expected field names, and a **[Transformer](../mapping_transformers.md#transformers)** when imported values must be converted or normalized.

### Header and first data row

Row 1 must contain the column names. Beneficiary data normally starts on row 2.

Set **First line** to the actual first data row when the workbook contains empty, explanatory, or other non-data rows after the header. For example, if rows 2-4 are empty and the first beneficiary record is on row 5, set **First line** to `5`.

### Record identifiers and Household membership

The identifier settings specify which workbook columns identify imported records.

| Program structure | Setting | Purpose |
| --- | --- | --- |
| Household-based | **Household ID column** | Identifies Households and links Individuals to them. The column must be present in both the `Households` and `Individuals` sheets. |
| Household-based | **Individual ID column** | Identifies records in the `Individuals` sheet. |
| People-only | **People ID column** | Identifies records in the `People` sheet. |

For a household-based import, each Individual row must contain a value in the configured **Household ID column**:

- if it matches an imported Household, the Individual becomes a member of that Household;
- if it does not match an imported Household, the Individual is imported without Household membership;
- if it is empty, the Individual row is not imported.

Household IDs must be unique in the `Households` sheet. Individual and People IDs must be unique in their respective sheets.

### Household role references

For household-based Programs, the **Head of Household** and **Primary Collector** fields must contain the `individual_id` of a record from the `Individuals` sheet. If provided, the **Alternate Collector** field must also contain the `individual_id` of a record from that sheet. During import, Country Workspace uses these values to link the created Individuals to the corresponding Household roles.

The Head of Household must belong to that Household. Primary and Alternate Collectors may belong to another Household in the same Batch or have no Household membership. The Primary Collector and Alternate Collector fields must not reference the same Individual.

### Supported workbook content

#### Embedded images

Images can be embedded directly in the workbook and imported as field values.

Place each image in the row of the corresponding beneficiary and anchor its top-left corner inside the target column. The column must match an image field in the Program's DataChecker, either directly or through a **[Mapping Importer](../mapping_transformers.md#mapping-importers)**. During import, Country Workspace extracts the image and uses it as the value of the corresponding field.

Alternatively, pictures can be added after the workbook has been imported by using the **Import pictures** action on the resulting Batch. See **[Import pictures](../picture_import.md)**.

#### Repeating fieldsets

Some beneficiary data is represented by repeating groups of related fields. For example, the **HOPE Document** and **HOPE Account** Fieldsets allow several documents or accounts to be imported for the same Individual.

Workbook columns must produce the field names expected by the Program's Individual DataChecker after any Mapping Importer is applied, including the configured Fieldset prefixes. See **[Fieldsets](../../data_validation/datachecker_configuration.md#fieldset)** and **[Prefixes](../../data_validation/datachecker_configuration.md#prefixes)** for details.

## Start an RDI import

1. Select the required **Office** and **[Program](../../program.md)**.
2. Open the Program page and select **Import Data**.
3. Use the **RDI** tab, which is selected by default.

The available settings depend on the beneficiary structure of the selected Program. Household-based Programs import Households and Individuals, while people-only Programs import People records without any Household data.

## Configure the import

### Batch and validation

**Batch name** becomes the name of the resulting **[Batch](../batches.md)**. If left empty, Country Workspace generates a default name.

**Validate after import** is enabled by default. When selected, Country Workspace schedules background validation jobs after the imported records have been created and processed using the selected Program's **[validation configuration](../../program.md#validation-configuration)**.

### Mapping and transformation

Select an optional **[Mapping Importer](../mapping_transformers.md#mapping-importers)** when source column names differ from the fields expected by the Program's DataCheckers. Mapping is applied while the source rows are processed.

Select an optional **[Transformer](../mapping_transformers.md#transformers)** when imported values must be converted or normalized. Transformers are applied after the beneficiary records have been created.

For household-based Programs, separate Mapping Importers and Transformers can be selected for Households and Individuals. For people-only Programs, the Individual Mapping Importer and Transformer are applied to People records.

Available Mapping Importers are limited to the selected Office and the corresponding Program DataChecker. Available Transformers are limited to the selected Office.

### Workbook settings

[Identifier fields](#record-identifiers-and-household-membership) and **Household label** refer to the original workbook column names, before any Mapping Importer is applied.

| Program structure | Setting | Default |
| --- | --- | --- |
| Household-based | **Household ID column** | `household_id` |
| Household-based | **Individual ID column** | `individual_id` |
| Household-based | **Household label** | `household_id` |
| People-only | **People ID column** | `pp_index_id` |
| People-only | **People prefix** | `pp_` |

For household-based Programs, **Household label** must specify an existing source column whose value will be used as the displayed Household name.

For people-only Programs, **People prefix** is removed, when present, from the beginning of each source column name before the record is processed.

Set **First line** to the first row containing beneficiary data, as described in [Header and first data row](#header-and-first-data-row).

### Start processing

Select the prepared Excel workbook in **File**, then select **Import**.

Country Workspace schedules a background import job. During processing, the job creates a **[Batch](../batches.md)** and adds the imported records to it.

## How RDI data is processed

RDI follows the general **[import lifecycle](../index.md#what-happens-during-import)**.

During source preparation, Country Workspace reads the required workbook sheets, normalizes column names, applies the selected Mapping Importers, processes supported document columns, applies Program defaults, and removes ignored fields.

It creates Households and Individuals, or People, from the workbook rows and stores each original source row for later Batch reprocessing.

After supported relationships and Transformers have been processed, RDI performs its source-specific **[duplicate identity check](#duplicate-identities)** before validation is scheduled.

### Beneficiary relationships

For household-based Programs, Households are created first. Individuals are then linked to them using the configured **[Household ID column](#record-identifiers-and-household-membership)**.

Country Workspace also links the [**Head of Household**, **Primary Collector**, and optional **Alternate Collector**](#household-role-references) to the corresponding imported Individuals.

People-only imports create People records without Household relationships.

### Duplicate identities

After any selected Transformers have been applied, Country Workspace checks the identity field configured in each relevant **[DataChecker](../../data_validation/datachecker_configuration.md#datachecker)**.

When the same non-empty identity value occurs more than once within the Batch, each affected record receives an identity error. This does not stop the import from completing.

This check covers duplicates within the imported Batch. Duplicate detection against records from other Batches is performed later by HOPE during merge processing.

This Batch-level check is separate from regular record validation.

Batch reprocessing clears existing errors, including duplicate identity errors, but does not run the duplicate identity check again.

### Validation after import

When **[Validate after import](#batch-and-validation)** is enabled, validation is scheduled after relationships, Transformers, and the duplicate identity check have been processed.

## Review the import results

Use the related background job to check whether the import completed successfully and to see the number of imported Households, Individuals, or People.

When the Batch status becomes **Complete**, open the created **[Batch](../batches.md)** to review its imported records. Duplicate identity errors are available after import processing, while validation results appear as the background validation jobs finish.

## Reprocess the Batch

An existing Batch can be reprocessed from the source data stored with its active records. Reprocessing can apply current **[Program defaults](../../program.md#default-values)** and newly selected **[Mapping Importers](../mapping_transformers.md#mapping-importers)** or **[Transformers](../mapping_transformers.md#transformers)** without uploading the workbook again.

See **[Reprocessing](../batches.md#reprocessing)** for details.

### Failed imports

Workbook reading and record creation run in one transaction. If either step fails, the Batch and its created records are rolled back.

If processing fails later during post-processing or validation scheduling, the created Batch can remain in **Loading** status.

## Troubleshooting

If an RDI import fails, review the related background job for the error details. Common causes include:

- a required workbook sheet is missing or has the wrong name;
- an identifier or Household label setting refers to a column that does not exist;
- the same Household, Individual, or People identifier occurs more than once in its sheet;
- a workbook row cannot be processed using the selected Program configuration.

Correct the workbook or import settings and start a new import. For background job, validation, and Batch-related issues, see **[Troubleshooting](../troubleshooting.md)**.
