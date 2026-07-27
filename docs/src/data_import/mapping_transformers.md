# Mapping Importers and Transformers

Mapping Importers and Transformers adapt source data to the structure and values expected by a **[Program](../program.md)**.

They perform different tasks:

| Component            | Purpose                                               | Applied                                     |
| -------------------- | ----------------------------------------------------- | ------------------------------------------- |
| **Mapping Importer** | Renames source fields                                 | While each source record is prepared        |
| **Transformer**      | Changes values, adds fields, or removes fields       | After beneficiary records have been created |

Both components are optional. Use them when the source data does not already match the Program's **[DataCheckers](../data_validation/datachecker_configuration.md#datachecker)**.

Mapping Importers and Transformers can be configured in either the **[Analyst / Collector Workspace](../interfaces.md#analyst--collector-workspace)** or **[Staff Administration](../interfaces.md#staff-administration)**. The available actions depend on the user's permissions.

## When to use each component

Use a **Mapping Importer** when a source field has the correct value but the wrong name. For example, it can rename `gender` to `sex`.

Use a **Transformer** when a value must be converted, calculated, combined, or removed. For example, it can replace `M` with `Male` in the `sex` field.

A common workflow uses both:

1. a Mapping Importer renames `gender` to `sex`;
2. a Transformer converts `M` to `Male`.

## Mapping Importers

A Mapping Importer renames fields from an external source to the field names expected by a Household or Individual **[DataChecker](../data_validation/datachecker_configuration.md#datachecker)**.

It changes field names only. It does not convert their values.

### Create a Mapping Importer

Open **Mapping Importers** in the **[Analyst / Collector Workspace](../interfaces.md#analyst--collector-workspace)** or **[Staff Administration](../interfaces.md#staff-administration)** and create a new entry.

Configure:

* **Name**: identifies the Mapping Importer and must be unique within the Office;
* **Description**: optionally explains its purpose or source;
* **DataChecker**: specifies whether the mapping is valid for the corresponding Household or Individual structure;
* **Rules**: defines the field-name changes.

A Mapping Importer belongs to one Office and one DataChecker.

When configuring it in the Analyst / Collector Workspace, the Office is taken from the selected working context. Only DataCheckers used by enabled Programs in that Office are available.

### Write mapping rules

Enter one rule per line using this format:

```text
source_field=target_field
```

For example:

```text
gender=sex
birthdate=date_of_birth
document_number=national_id_document_number
```

Each rule must:

* contain exactly one `=`;
* include a source and target field;
* use different source and target names.

Empty lines are ignored.

The rules above change this record:

```text
gender: M
birthdate: 2000-05-16
document_number: ID-987654
```

to:

```text
sex: M
date_of_birth: 2000-05-16
national_id_document_number: ID-987654
```

A rule is applied only when the source field exists in the record. Other fields remain unchanged.

If the target field already exists, its value is replaced by the value from the source field.

### Source field names

Mapping is applied after source-specific preparation and field-name normalization.

Rules must therefore use the field names produced by the source before mapping:

* RDI rules use workbook column names after the People prefix has been removed, when applicable, and the names have been normalized;
* Aurora rules use the prepared Aurora field names;
* Kobo rules use question names after supported group paths have been removed.

See **[Data sources](sources/index.md)** for the processing rules of each source.

For repeating Fieldsets, the mapped target names must include the prefixes expected by the DataChecker. See **[Fieldsets](../data_validation/datachecker_configuration.md#fieldset)** and **[Prefixes](../data_validation/datachecker_configuration.md#prefixes)**.

### Use a Mapping Importer during import

Mapping Importers can be selected when importing data from **[RDI](sources/xlsx.md)**, **[Aurora](sources/aurora.md)**, or **[Kobo](sources/kobo.md)**.

Available Mapping Importers are limited to:

* the selected Office;
* the DataChecker used by the selected Program for that beneficiary type.

For a household-based Program, separate Mapping Importers can be selected for Households and Individuals.

For a people-only Program, the Individual Mapping Importer is applied to People records.

### Apply a Mapping Importer to an existing Batch

A Mapping Importer cannot be applied directly to records in an existing **[Batch](batches.md)**.

Use **[Batch reprocessing](batches.md#reprocessing)** to rebuild the beneficiary fields from their stored source data and apply the selected Mapping Importer.

Reprocessing uses the current rules saved in the Mapping Importer. Changes made in the original source after the import are not retrieved.

Records already pushed to HOPE are excluded from reprocessing.

## Transformers

A Transformer uses JavaScript to change the processed fields of a Household, Individual, or Person.

Unlike a Mapping Importer, a Transformer can:

* convert values;
* add or remove fields;
* calculate a field from other fields;
* apply conditional rules;
* update several fields together.

A Transformer belongs to one Office but is not tied to a specific DataChecker. Ensure that its code supports the beneficiary type and fields to which it will be applied.

### Create a Transformer

Open **Transformers** in the **[Analyst / Collector Workspace](../interfaces.md#analyst--collector-workspace)** or **[Staff Administration](../interfaces.md#staff-administration)** and create a new entry.

Configure:

* **Name**: identifies the Transformer and must be unique within the Office;
* **Description**: optionally explains the transformation;
* **Value transformations**: contains the JavaScript code.

### Write transformation code

Define the transformation as a JavaScript function using this format. Country Workspace passes one beneficiary record to the function, which must return the updated record as an object:

```javascript
function transform(record) {
    // Update the record.
    return record;
}
```

For example, this Transformer normalizes a value:

```javascript
function transform(record) {
    if (record.sex === "M") {
        record.sex = "Male";
    }

    if (record.sex === "F") {
        record.sex = "Female";
    }

    return record;
}
```

With this input:

```json
{
  "individual_id": 1042,
  "sex": "M"
}
```

the function returns:

```json
{
  "individual_id": 1042,
  "sex": "Male"
}
```

The returned object replaces the current processed fields of the record. Preserve every field that must remain available.

### Verify a Transformer

In **[Staff Administration](../interfaces.md#staff-administration)**, open an existing Transformer and select **Edit & Verify Code**.

To verify the transformation from the previous example:

* enter its JavaScript in **Code to write**;
* enter this sample record as a JSON object in **Input data**:

```json
{
  "sex": "M",
  "age": 25
}
```

Run the verification and review **Output** before saving the code. The returned `sex` value should be `Male`.

The input must be a JSON object, not a list or individual value.

If the output is unchanged, check whether:

* the input satisfies the conditions in the function;
* the field names match the processed record;
* the function returns the updated record.

### Use a Transformer during import

Transformers can be selected during **[RDI](sources/xlsx.md)**, **[Aurora](sources/aurora.md)**, and **[Kobo](sources/kobo.md)** imports.

They are applied after beneficiary records have been created and supported relationships have been processed.

For a household-based Program, separate Transformers can be selected for Households and Individuals.

For a people-only Program, the Individual Transformer is applied to People records.

Available Transformers are limited to the selected Office.

When **[Validate after import](../program.md#validation-configuration)** is enabled, validation is scheduled after the Transformer has been applied.

### Use a Transformer during reprocessing

A Transformer can also be selected during **[Batch reprocessing](batches.md#reprocessing)**.

Reprocessing first rebuilds the beneficiary fields from the stored source data, applies the selected Mapping Importers and import rules, refreshes supported Household role and collector references, and then applies the selected Transformers.

Validation is scheduled after reprocessing.

### Run a Transformer on existing records

A Transformer can be applied without rebuilding the records from their source data.

Open the Transformer in the **[Analyst / Collector Workspace](../interfaces.md#analyst--collector-workspace)** and select **Run Formula on Existing Records**.

Then:

1. select the required Batch;
2. select whether to apply it to Households, Individuals, or both;
3. confirm the operation.

For a people-only Program, the Transformer can be applied only to People records through the Individual option.

Country Workspace schedules the operation as a background job. Only records that have not already been pushed to HOPE are processed.

A record is saved only when the Transformer changes its processed fields. Previous validation results are cleared for changed records, but new validation is not scheduled automatically.

Validate the affected records separately when updated validation results are required.

## Apply updated mappings and transformations

Changing a Mapping Importer or Transformer does not automatically update previously imported records.

To apply updated configuration:

* use **[Batch reprocessing](batches.md#reprocessing)** when the records must be rebuilt from stored source data, remapped, transformed, and validated;
* use **Run Formula on Existing Records** when only a Transformer must be applied to the current processed fields.

Review the resulting background job to confirm that processing completed successfully.

## Troubleshooting

Most problems relate to one of these areas:

* **Mapping availability**: the Mapping Importer belongs to another Office or is linked to a DataChecker not used by the selected Program.
* **Mapping results**: the rule uses the wrong prepared source-field name, the source field is missing, or another rule replaces the same target field.
* **Transformer code**: the JavaScript does not define a function in a supported format, the function does not return an object, or its conditions do not match the record data.
* **Existing records**: records already pushed to HOPE are excluded, and standalone Transformer execution does not schedule validation.

For source-specific field preparation, see **[Data sources](sources/index.md)**.

For problems applying updated configuration to an existing Batch, see **[Batch reprocessing](batches.md#reprocessing)**.

For general import issues, see **[Troubleshooting](troubleshooting.md)**.
