# Program

A **Program** represents a campaign or intervention targeting a specific group of beneficiaries for a specific operational need, such as *Cash for Nutrition* or *Emergency Food Assistance*.

Within the **[Analyst / Collector Workspace](../interfaces.md#analyst--collector-workspace)**, the selected Program becomes the working context for beneficiary management. Imports, beneficiary records, Batches, validation, and related workflows all operate within the currently selected Program.

## What a Program defines

A Program defines how beneficiary data is imported, validated, and displayed.

### Beneficiary structure

A Program inherits its beneficiary structure from the selected **Beneficiary Group**.

Two structures are supported:

- **Household-based** — each Household contains one or more Individuals.
- **People-only** — Individuals are managed without Households.

The selected structure determines how beneficiary data is imported, validated, managed, and displayed throughout the workspace.

### Validation configuration

Validation is based on:

- **[DataCheckers](data_validation/datachecker_configuration.md)** that define the expected beneficiary fields;
- a beneficiary validator that performs additional validation of the beneficiary structure;
- the **[Alien validation](data_validation/alien_fields.md)** setting, which controls how unexpected source fields are handled during import.

Validation is performed after import, as described in **[Data Import](index.md)**.

See **[Alien Fields](data_validation/alien_fields.md)** for more information about alien validation.

### Default values

Programs can define default values for Households and Individuals.

These values are applied during **[Data Import](index.md)** when the corresponding beneficiary field has no value.

### Display configuration

A Program defines which beneficiary fields are displayed in the Analyst / Collector Workspace.

Display settings determine which beneficiary fields are shown in the workspace. They do not affect imported or stored data.

### Alien columns to ignore

Programs can define source columns that should be ignored during import instead of being treated as alien fields.

This is useful when imported files contain additional columns that are not required by the Program.

See **[Alien Fields](data_validation/alien_fields.md)** for more information.

### Deduplication settings

For Programs with **Biometric deduplication enabled**, the Program page displays the current deduplication settings retrieved from DedupEngine in real time.

If DedupEngine is unavailable, the settings may be displayed as `N/A`.

## Start an import

Imports are normally started from the Program page by selecting **Import Data**.

The import always uses the currently selected Program and creates a **[Batch](batches.md)** containing the imported records.

For an overview of the import workflow, see **[Data Import](index.md)**. Source-specific instructions are available in **[Data sources](sources/index.md)**.

## After import

After an import completes:

- imported beneficiary records become available within the selected Program;
- validation results become available after validation finishes;
- the created **[Batch](batches.md)** can be reviewed and, if necessary, reprocessed.

See **[Batches](batches.md)** to review import results, monitor validation, and reprocess existing Batches.
