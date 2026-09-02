# Kobo

Kobo imports household-based beneficiary registrations from a Kobo project into the selected **[Program](../../program.md)**.

Each Kobo submission creates one Household. Individual records are read from a repeat-group field within that submission; unless they are **[external collectors](#external-collectors)**, they become members of the created Household.

The expected question names, value types, required fields, and validation rules depend on the Program's **[DataCheckers](../../data_validation/datachecker_configuration.md)**.

## Prepare the Kobo project

### Project availability

The Kobo project must be deployed and available through the Kobo connection configured for the selected Office.

The Office must have a Kobo country code configured. Country Workspace uses this configuration to load the Kobo projects available for import.

Only deployed survey projects are shown in the **Project** field.

### Submission structure

Each Kobo submission represents one Household.

Household data is read from the top-level submission fields. The field configured as **Individual records field** is excluded from the Household data and processed separately.

That field must contain a repeat group in which each item represents one Individual:

```text
Submission
├── Household questions
└── individual_questions
    ├── Individual 1
    ├── Individual 2
    └── Individual 3
```

By default, Country Workspace expects the repeat-group field to be named `individual_questions`.

If the configured field is missing or empty, the Household is imported without Individuals.

Top-level Kobo metadata fields whose names start with `_` are not imported as beneficiary fields. Kobo-specific system questions whose final field name starts with `kobo_sys__` are also excluded during processing.

### Questions and values

Kobo questions represent beneficiary fields configured in the Program's **[DataCheckers](../../data_validation/datachecker_configuration.md)**.

Country Workspace removes Kobo group paths from question names before processing them. For example:

```text
household/location/village
```

is processed as:

```text
village
```

Question names must therefore produce the field names expected by the corresponding Household or Individual DataChecker after the group path has been removed.

Use a **[Mapping Importer](../mapping_transformers.md#mapping-importers)** when the resulting Kobo question names differ from the expected DataChecker fields. Use a **[Transformer](../mapping_transformers.md#transformers)** when imported values must be converted or normalized.

### Record identifiers

Country Workspace generates a sequential `household_id` for every imported Household. A Kobo question is not used as the Household identifier.

Country Workspace also stores a source identifier based on the Kobo project and submission ID. Individual source identifiers are based on the same submission ID together with the Individual's position in the repeat group.

These source identifiers are used internally to trace records to their Kobo submissions.

### Household roles

Household roles are determined from the processed Individual fields within each submission.

After Mapping Importers and field normalization have been applied:

* the first Individual whose `relationship` is `HEAD` becomes the Head of Household;
* the first Individual whose `role` is `PRIMARY` becomes the Primary Collector;
* the first Individual whose `role` is `ALTERNATE` becomes the Alternate Collector.

The role records must be included in the submission's configured Individual repeat group. When the selected record is an external collector, the Household role points to the shared record described in **[External collectors](#external-collectors)**.

If no matching Individual is present, the corresponding Household role is left empty.

### External collectors

An Individual whose `relationship` is `NON_BENEFICIARY` is treated as an external collector: a person who collects on behalf of a Household without being counted as one of its members.

External collectors are not stored as Household members. Country Workspace creates them without a Household. Their direct Household links are the Primary Collector and Alternate Collector role references.

### Collector references

An Individual can contain a `collector_id` value referencing another imported Individual.

After all submissions have been processed, Country Workspace compares `collector_id` with the imported `individual_id` and `index_id` values. When a matching Individual is found, the source value is replaced with a link to that Individual.

The referenced Individual can belong to another Household in the same Batch, or can be a shared external collector stored without a Household in the same Program, even if that collector was imported in an earlier Batch.

### Attachments

Kobo attachments are downloaded during import and added to the corresponding submission question.

Attachments are supported both for top-level Household questions and for questions inside the Individual repeat group.

The Kobo question must map directly, or through a **[Mapping Importer](../mapping_transformers.md#mapping-importers)**, to a compatible field in the corresponding Program DataChecker.

Country Workspace stores the downloaded attachment content with its media type so that supported image or file fields can process it as part of the beneficiary record.

### Repeating fieldsets

Some beneficiary data is represented by repeating groups of related fields. For example, the **HOPE Document** and **HOPE Account** Fieldsets allow several documents or accounts to be imported for the same Individual.

Kobo question names must produce the field names expected by the Program's DataChecker after group paths and any Mapping Importer have been processed, including the configured Fieldset prefixes.

See **[Fieldsets](../../data_validation/datachecker_configuration.md#fieldset)** and **[Prefixes](../../data_validation/datachecker_configuration.md#prefixes)** for details.

Kobo questions can also use the supported numbered document-field format, such as:

```text
document_1_type
document_1_number
document_1_country
document_1_expire_date
```

Country Workspace converts these questions into the corresponding repeating document data during import.

Kobo questions can also use the HOPE Core account naming convention, such as:

```text
account__mobile__number
account__mobile__financial_institution
account__mobile__provider
account__bank__number
```

Country Workspace automatically converts these `account__{type}__{field}` questions into the fields expected by the **HOPE Account** Fieldset:

* `account__{type}__number` becomes `{type}_number`;
* `account__{type}__financial_institution` becomes `{type}_financial_institution`;
* any other `account__{type}__{field}` question is collected into the `{type}_data` JSON field.

This conversion happens automatically for every import source (Kobo, xlsx/RDI, and Aurora) and does not require a Mapping Importer or Program default field, as long as the question name already matches the `account__{type}__{field}` convention above. Use a **[Mapping Importer](../mapping_transformers.md#mapping-importers)** to rename a differently named question (for example `financial_institution_pk`) to the expected field name first.

## Start a Kobo import

1. Select the required **Office** and **[Program](../../program.md)**.
2. Open the Program page and select **Import Data**.
3. Select the **Kobo** tab.

The Kobo import expects a household-based source structure in which each submission represents one Household and its Individuals are stored in a repeat-group field.

## Configure the import

### Batch and validation

**Batch name** becomes the name of the resulting **[Batch](../batches.md)**. If left empty, Country Workspace generates a default name.

**Validate after import** is enabled by default. When selected, Country Workspace schedules background validation jobs after all Kobo submissions have been imported and post-processing has completed.

Validation uses the selected Program's **[validation configuration](../../program.md#validation-configuration)**.

### Mapping and transformation

Select an optional **[Mapping Importer](../mapping_transformers.md#mapping-importers)** when Kobo question names differ from the fields expected by the Program's DataCheckers. Mapping is applied while each submission is processed.

Select an optional **[Transformer](../mapping_transformers.md#transformers)** when imported values must be converted or normalized. Transformers are applied after all new submissions have been imported.

Separate Mapping Importers and Transformers can be selected for Households and Individuals.

Available Mapping Importers are limited to the selected Office and the corresponding Program DataChecker. Available Transformers are limited to the selected Office.

### Kobo settings

**Project** specifies the deployed Kobo project from which submissions will be imported.

The available projects are loaded from the Kobo connection configured for the selected Office.

**Individual records field** specifies the repeat-group field containing the Individual records within each submission.

The default value is:

```text
individual_questions
```

Change it when the Kobo form uses a different repeat-group field.

The field name refers to the original top-level Kobo submission field before the Individual records are processed.

### Start processing

Select **Import** after configuring the source and processing settings.

Country Workspace schedules a background Kobo import job. No file upload is required.

During processing, the job creates a **[Batch](../batches.md)** and imports the available Kobo submissions into it.

## How Kobo data is processed

Kobo follows the general **[import lifecycle](../index.md#what-happens-during-import)**.

Source preparation includes downloading attachments, removing Kobo metadata and system questions, removing group paths from question names, normalizing field names and selected values, applying Mapping Importers, processing supported document and account questions, applying Program defaults, and removing ignored fields.

Country Workspace creates one Household for each submission and processes one Individual entry for each item in the configured repeat group. Regular Individuals are created as Household members; matching external collectors reuse the existing Program-wide record. The source fields used for each imported record are stored for later Batch reprocessing.

Household membership and roles are created from each submission. After all submissions have been processed, supported collector references are resolved and the selected Transformers are applied.

### Incremental import

Kobo import is incremental.

Country Workspace records the ID of the last successfully imported submission separately for each Program and Kobo project. A later import requests only submissions whose Kobo submission ID is greater than that stored ID.

As a result:

* the first import processes all available submissions;
* later imports process only newly created submissions;
* submissions that were already imported are not created again;
* changes to an already imported Kobo submission are not synchronized automatically;
* deleting a previously imported submission in Kobo does not remove its Country Workspace records.

Use **[Batch reprocessing](#reprocess-the-batch)** to reapply current Program processing rules to the source data already stored in Country Workspace. Reprocessing does not download an updated version of the submission from Kobo.

### Partial imports and continuation

Each Kobo submission is processed in its own database transaction.

If a submission fails:

* the failing submission is rolled back;
* submissions completed before it remain imported;
* Country Workspace records the last successfully completed submission ID;
* the failed submission can be processed again during a retry or later import.

For large projects, processing may be divided between several background jobs. When the configured processing period is reached, Country Workspace schedules another job for the same Batch and continues with the next submission.

The Batch remains in **Loading** status while continuation jobs are running. Household membership and Household roles are created as each submission is imported. Batch-level collector links, Transformers, validation, and final Batch completion are processed only after all available submissions have been imported.

### Beneficiary relationships

Each Individual is linked to the Household created from the same submission, except for external collectors, which are kept without a Household as described in **[External collectors](#external-collectors)**.

Household roles are assigned as described in **[Household roles](#household-roles)**. Supported cross-record collector references are resolved as described in **[Collector references](#collector-references)**.

### Duplicate identities

Apart from external collectors, the current Kobo import flow does not perform duplicate identity detection.

Regular validation checks each record separately and does not detect identity collisions between records.

### Validation after import

When **[Validate after import](#batch-and-validation)** is enabled, validation is scheduled after Household roles, collector references, and Transformers have been processed.

## Review the import results

Use the related background jobs to check whether the import completed successfully and to see how many Households and Individuals each job imported.

A large import may have several consecutive background jobs associated with the same Batch.

When the Batch status becomes **Complete**, open the created **[Batch](../batches.md)** to review its imported records. Validation results appear as the background validation jobs finish.

If there were no submissions newer than the last successfully imported Kobo submission, the import can complete with an empty Batch.

## Reprocess the Batch

An existing Kobo Batch can be reprocessed from the source data stored with its active records.

Reprocessing can apply current **[Program defaults](../../program.md#default-values)** and newly selected **[Mapping Importers](../mapping_transformers.md#mapping-importers)** or **[Transformers](../mapping_transformers.md#transformers)** without requesting the submissions from Kobo again.

See **[Reprocessing](../batches.md#reprocessing)** for details.

## Troubleshooting

If a Kobo import cannot be started or fails during processing, check the import form and the related background job for error details. Common causes include:

* the selected Office does not have a Kobo country code configured;
* the Kobo connection cannot access the project;
* the project is not deployed or is not available for the selected Office;
* a Kobo question or value cannot be processed using the selected Program configuration;
* a Mapping Importer produces fields that are incompatible with the Program DataChecker;
* a referenced Kobo attachment cannot be downloaded;
* the Kobo service is temporarily unavailable.

If Households are imported without their Individuals, verify that **Individual records field** matches the repeat-group field used by the Kobo project.

When processing fails on a submission, the job error identifies the failed submission and the last successfully imported submission. Successfully completed submissions remain stored, and later processing resumes after the recorded successful submission.

Correct the Kobo project data, Office configuration, or import settings, then retry the import or start another import.

For background job, validation, and Batch-related issues, see **[Troubleshooting](../troubleshooting.md)**.
