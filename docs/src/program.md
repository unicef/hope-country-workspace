# Program

A **Program** represents a campaign or intervention targeting a specific group of beneficiaries for a specific operational need, such as *Cash for Nutrition* or *Emergency Food Assistance*.

Within the [Analyst / Collector Workspace](interfaces.md#analyst-collector-workspace), the selected Program becomes the working context for beneficiary management. Imports, beneficiary records, Batches, validation, and related workflows all operate within the currently selected Program.

## What a Program defines

A Program defines how beneficiary data is imported, validated, displayed, and processed before transfer to HOPE Core.

### Beneficiary structure

A Program inherits its beneficiary structure from the selected **Beneficiary Group**.

Two structures are supported:

- **Household-based**: each Household contains one or more Individuals.
- **People-only**: Individuals are managed without Households.

The selected structure determines how beneficiary data is imported, validated, managed, and displayed throughout the workspace.

### Validation configuration

Validation is based on:

- **[DataCheckers](data_validation/datachecker_configuration.md)** that define the expected beneficiary fields;
- a beneficiary validator that performs additional validation of the beneficiary structure;
- the **[Alien validation enabled](data_validation/alien_fields.md)** setting, which controls whether unexpected processed fields are checked during validation;
- the **[Alien columns to ignore](#alien-columns-to-ignore)** lists.

After import, validation is scheduled when **[Validate after import](data_import/index.md#validation-after-import)** is enabled.

See **[Alien Fields](data_validation/alien_fields.md)** for more information.

### Default values

Programs can define default values for Households and Individuals.

These values are applied during **[Data Import](data_import/index.md)** when the corresponding beneficiary field is missing or has a null value. They help ensure that required beneficiary fields are populated consistently.

### Display configuration

A Program defines which beneficiary fields are displayed in the [Analyst / Collector Workspace](interfaces.md#analyst-collector-workspace).

Display settings affect only the user interface and do not influence imported or stored data.

### Alien columns to ignore

Programs can define processed fields that should be excluded from Alien Field validation.

During import and reprocessing, matching fields are also removed before Transformers are applied.

See **[Alien Fields](data_validation/alien_fields.md)** for configuration and processing details.

### RDP operations

The **RDP Operations** section on the Program page defines which **[RDP operations](rdp/operations/index.md)** are available when creating an RDP.

- **[OCR](rdp/operations/ocr.md)** and **[biographic deduplication](rdp/operations/biographic-deduplication.md)** are enabled by default and can be disabled independently in Country Workspace.
- **[Biometric deduplication](rdp/operations/biometric-deduplication.md)** is controlled by HOPE. When enabled, it is displayed as a checked, read-only checkbox.

Users with permission to change the Program can update the CW-managed operation configuration only while no RDP exists for the Program. Once any RDP exists, including a `CANCELLED` RDP, the operation checkboxes become read-only.

See **[Create an RDP](rdp/create.md#configure-rdp-processing)** for operation selection and review thresholds.

### Biometric deduplication settings

For Programs with biometric deduplication enabled, the **Biometric Deduplication Settings** section displays the current deduplication settings retrieved from DedupEngine in real time.

The settings are not stored in the Country Workspace database. When permitted by the current policy, use **Update Biometric Dedup Settings** to update them directly in DedupEngine.

If DedupEngine is unavailable, the settings may be displayed as `N/A`.

Biographic matching sensitivity is configured in DedupEngine and is not shown on the Program page. See **[Biographic deduplication](rdp/operations/biographic-deduplication.md)**.

## Start an import

Imports are normally started from the Program page by selecting **Import Data**.

The import always uses the currently selected Program and creates a **[Batch](data_import/batches.md)** containing the imported records for that Program.

For an overview of the import workflow, see **[Data Import](data_import/index.md)**. Source-specific instructions are available in **[Data sources](data_import/sources/index.md)**.

## After import

After an import completes:

- imported beneficiary records become available within the selected Program;
- validation results become available after any scheduled validation finishes;
- the created **[Batch](data_import/batches.md)** can be reviewed and, if necessary, reprocessed.

See **[Batches](data_import/batches.md)** to review import results, monitor validation, and reprocess existing Batches.
