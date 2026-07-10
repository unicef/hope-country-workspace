# Data Import

Country Workspace supports importing beneficiary data from multiple sources. Every import runs within the selected **[Program](program.md)** and creates a **[Batch](batches.md)** that groups the imported records.

This section explains how to prepare a Program, choose and configure a data source, review imported records, reprocess existing Batches, and resolve common import issues.

## Import workflow

```mermaid
flowchart LR
    A[Select Program]
        --> B[Choose data source]
        --> C[Configure import]
        --> D[Import data]
        --> E[Review imported records]
```

## Before you import

Before importing beneficiary data, make sure that the selected **[Program](program.md)** is configured for the required beneficiary structure and validation rules.

Depending on the selected source, additional preparation may be required. Source-specific requirements and instructions are described in **[Data sources](sources/index.md)**.

Optional field mappings and value transformations are described in **[Mapping and transformation](mapping_transformers.md)**.

## What happens during import

Although each data source has its own import process, all imports follow the same high-level workflow.

```mermaid
flowchart LR
    A[Read source data]
        --> B[Process data]
        --> C[Create beneficiary records]
        --> D[Complete import]
```

Source-specific processing is described in the corresponding pages of the **[Data sources](sources/index.md)** section.

### Validation after import

By default, imported records are validated after they have been created and processed. Validation results become available when validation finishes. Validation can be disabled when configuring the import.

## Import results

After an import completes:

- imported beneficiary records become available for review;
- a **[Batch](batches.md)** is created to group all imported records and record the import results;
- if import settings change later, the Batch can be reprocessed without importing the source data again.

Batch review, validation status, and reprocessing are described in **[Batches](batches.md)**.

## Supported data sources

Country Workspace currently supports importing beneficiary data from:

- **[Aurora](sources/aurora.md)**;
- **[Excel files](sources/xlsx.md)**;
- **[Kobo](sources/kobo.md)**.

An overview of the available sources and their requirements is provided in **[Data sources](sources/index.md)**.

## Troubleshooting

If an import cannot be started, does not complete, or produces unexpected records, see **[Troubleshooting](troubleshooting.md)**.
