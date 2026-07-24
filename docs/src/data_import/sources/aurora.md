# Aurora

Aurora imports beneficiary registrations from a selected Aurora Registration into the selected **[Program](../../program.md)**.

For a household-based Program, each Aurora record creates one Household and its related Individuals. For a people-only Program, each Aurora record creates one Person.

The expected field names, value types, required fields, and validation rules depend on the Program's **[DataCheckers](../../data_validation/datachecker_configuration.md)**.

## Prepare the Aurora source

### Project and Registration availability

Aurora Projects and Registrations are synchronized from Aurora and cannot be created manually in Country Workspace.

Before starting an import:

1. Synchronize Aurora Projects and Registrations from the Aurora Project administration page.
2. Open the synchronized Aurora Project and link it to the corresponding **[Program](../../program.md)**.
3. If the Registration uses encrypted data, open the synchronized Registration and configure its RSA private key.

Only active Registrations whose Aurora Project is linked to the selected Program are available in the **Registration** field.

Country Workspace must also be configured with access to the Aurora API.

### Encrypted registrations

Aurora can provide either merged registration data or an encrypted payload.

When an RSA private key is configured on the selected Registration, Country Workspace requests the encrypted representation and decrypts its field and file data before processing the record.

The key must be a valid unencrypted RSA private key in PEM format. The stored key is not displayed again in the administration form.

When no private key is configured, Country Workspace requests the full merged registration data from Aurora. The import fails if Aurora does not allow Country Workspace to access that data.

### Record identifiers

Each Aurora record must contain a numeric `pk`.

Country Workspace uses this value to:

* identify records that have already been imported;
* resume later imports after the last successful record;
* create an internal source identifier for each imported beneficiary.

For household-based Programs, the created Household and Individuals receive source identifiers derived from the Aurora record `pk` and their position within that record.

### Household-based record structure

For a household-based Program, each Aurora record creates exactly one Household.

Country Workspace recognizes the following fields as the Household group:

```text
household
household-info
household_info
```

The Household group may contain either one object or a list. When it contains a list, only its first item is used for the Household.

Country Workspace recognizes the following fields as the Individual group:

```text
individuals
individual-details
individual_details
```

The Individual group may contain one object or a list of objects. Each object creates one Individual linked to the Household from the same Aurora record.

An Aurora record can therefore have a structure similar to:

```text
Record
├── Shared fields
├── household
│   └── Household fields
└── individuals
    ├── Individual 1
    ├── Individual 2
    └── Individual 3
```

Top-level fields outside the supported Household and Individual groups are treated as shared fields. They are added to the created Household and to every Individual from that record.

Values inside the Household or Individual group override shared fields with the same name.

If no supported Household group is present, Country Workspace still creates a Household from the shared fields. If no supported Individual group is present, the Household is imported without Individuals.

### People-only record structure

For a people-only Program, each Aurora record creates one Person without a Household relationship.

The prepared field data from the Aurora record is processed using the Program's Individual DataChecker, Mapping Importer, and Transformer configuration.

### Fields and values

Aurora field names must produce the names expected by the corresponding Household or Individual DataChecker after source processing.

Top-level nested objects are expanded by prefixing their child fields with the parent name. For example:

```text
address:
    city: Kyiv
```

is processed as:

```text
address_city: Kyiv
```

Country Workspace also generates `full_name` when it is empty and the record contains one or more of:

```text
given_name
middle_name
family_name
```

Use a **[Mapping Importer](../mapping_transformers.md#mapping-importers)** when the processed Aurora field names differ from the fields expected by the Program's DataCheckers.

Use a **[Transformer](../mapping_transformers.md#transformers)** when imported values must be converted or normalized.

### Files and repeating fieldsets

For encrypted registrations, Aurora field data and file data are decrypted separately and merged before the beneficiary record is processed.

File values must correspond directly, or through a **[Mapping Importer](../mapping_transformers.md#mapping-importers)**, to compatible fields in the corresponding Program DataChecker.

Aurora fields can also produce the names expected by repeating **[Fieldsets](../../data_validation/datachecker_configuration.md#fieldset)**, including their configured **[Prefixes](../../data_validation/datachecker_configuration.md#prefixes)**.

The supported numbered document-field format can be used to create repeating document data:

```text
document_1_type
document_1_number
document_1_country
document_1_expire_date
```

## Start an Aurora import

1. Select the required **Office** and **[Program](../../program.md)**.
2. Open the Program page and select **Import Data**.
3. Select the **Aurora** tab.

The fields available on the import form depend on whether the selected Program is household-based or people-only.

## Configure the import

### Batch and validation

**Batch name** becomes the name of the resulting **[Batch](../batches.md)**. If left empty, Country Workspace generates a default name.

**Validate after import** is enabled by default. When selected, Country Workspace schedules background validation jobs after the imported records have been processed.

Validation uses the selected Program's **[validation configuration](../../program.md#validation-configuration)**.

### Mapping and transformation

Select an optional **[Mapping Importer](../mapping_transformers.md#mapping-importers)** when Aurora field names differ from the fields expected by the Program's DataCheckers. Mapping is applied while each source record is processed.

Select an optional **[Transformer](../mapping_transformers.md#transformers)** when imported values must be converted or normalized. Transformers are applied after all new Aurora records have been imported.

For household-based Programs, separate Mapping Importers and Transformers can be selected for Households and Individuals.

For people-only Programs, the Individual Mapping Importer and Transformer are applied to People records.

Available Mapping Importers are limited to the selected Office and the corresponding Program DataChecker. Available Transformers are limited to the selected Office.

### Aurora settings

**Registration** specifies the Aurora Registration whose records will be imported.

Only active Registrations linked through an Aurora Project to the selected Program are available.

### Start processing

Select **Import** after configuring the source and processing settings.

Country Workspace schedules a background Aurora import job. No file upload is required.

During processing, the job creates a **[Batch](../batches.md)** and imports the available Aurora records into it.

## How Aurora data is processed

Aurora follows the general **[import lifecycle](../index.md#what-happens-during-import)**.

Source preparation includes decrypting protected field and file data when required, separating Household and Individual groups, combining them with shared fields, flattening supported nested values, normalizing field names, applying Mapping Importers, processing supported document fields, applying Program defaults, and removing ignored fields.

Country Workspace then creates one Person for each Aurora record in a people-only Program, or one Household and its supported Individuals in a household-based Program.

The prepared source data is stored with each beneficiary record. After all records have been imported, supported collector references are resolved and the selected Transformers are applied.

### Incremental import

Aurora import is incremental.

Country Workspace records the ID of the last successfully imported Aurora record separately for each selected Program and Registration.

During later imports, records whose `pk` is not greater than the stored record ID are skipped.

As a result:

* the first import processes records that have not previously been imported;
* later imports process only records with a higher `pk`;
* previously imported records are not created again;
* changes to a record that keeps the same `pk` are not synchronized automatically;
* deleting a previously imported record in Aurora does not remove its Country Workspace record.

A new Batch is created for every Aurora import, including an import in which no new records are found.

### Partial imports

Each Aurora record is processed in its own database transaction.

If a record fails:

* the failing record is rolled back;
* records completed earlier in the job remain imported;
* Country Workspace preserves the last successfully imported record ID;
* the current Batch remains in **Loading** status because final post-processing is not completed.

A later import creates a new Batch and skips the record IDs already stored as successfully imported. Records imported before a failure and records imported during a later attempt can therefore belong to different Batches.

Review the failed background job to find the failed Aurora record and the last successfully imported record ID.

### Beneficiary relationships

For household-based Programs, each imported Individual is linked directly to the Household created from the same Aurora record.

The current Aurora import flow does not assign the **Head of Household**, **Primary Collector**, or **Alternate Collector** from the Household and Individual groups.

After all records have been imported, supported `collector_id` values are resolved against imported `individual_id` and `index_id` values within the Batch.

People-only imports create People records without Household relationships.

### Duplicate identities

The current Aurora import flow does not perform duplicate identity detection.

Regular validation checks each record separately and does not detect identity collisions between records.

### Validation after import

When **[Validate after import](#batch-and-validation)** is enabled, validation is scheduled after collector references and Transformers have been processed.

## Review the import results

Use the related background job to check whether the import completed successfully and to see the number of imported Households and Individuals for a household-based Program, or People for a people-only Program.

When the Batch status becomes **Complete**, open the created **[Batch](../batches.md)** to review its imported records. Validation results appear as the background validation jobs finish.

If there were no Aurora records newer than the last successfully imported record, the import can complete with an empty Batch.

## Reprocess the Batch

An existing Aurora Batch can be reprocessed from the source data stored with its active records.

Reprocessing can apply current **[Program defaults](../../program.md#default-values)** and newly selected **[Mapping Importers](../mapping_transformers.md#mapping-importers)** or **[Transformers](../mapping_transformers.md#transformers)** without requesting the records from Aurora again.

See **[Reprocessing](../batches.md#reprocessing)** for details.

## Troubleshooting

If an Aurora import cannot be started or fails during processing, check the import form and the related background job for error details. Common causes include:

* the Aurora API URL or API token is not configured correctly;
* Aurora Projects or Registrations have not been synchronized;
* the synchronized Aurora Project has not been linked to the selected Program;
* the Registration is inactive;
* Aurora does not allow access to the full merged data and no RSA private key is configured;
* the encrypted payload cannot be decrypted with the configured RSA private key or uses an unsupported encryption method;
* an Aurora record does not contain a valid numeric `pk`;
* an Aurora field or value cannot be processed using the selected Program configuration;
* a Mapping Importer produces fields that are incompatible with the Program DataChecker;
* the Aurora service is temporarily unavailable or returns an invalid response.

If a Household is imported without the expected Household data or Individuals, verify that the Aurora record uses one of the supported Household and Individual group names.

When processing fails on a record, successfully completed records remain stored and the related job identifies the failed record and the last successfully imported record ID.

Correct the Aurora source data, connection, Registration configuration, or import settings, then start another import.

For background job, validation, and Batch-related issues, see **[Troubleshooting](../troubleshooting.md)**.
