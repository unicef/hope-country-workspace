# User Roles and Permissions

Proper user role and permission configuration ensures that users have appropriate access levels based on their responsibilities.

## Understanding the Permission System

Permissions in Country Workspace are organized through **Groups** and the **User Role** table, not through the Django user model directly.

The main idea is that **permissions are per office or per program within a specific office**.

### How Permissions Work

1. **Create a Group** with specific permissions
2. **Assign the Group to a User** via the User Role table for a specific office and optionally a specific program
3. The permissions control:
    - Which country offices a user can access
    - Which programs within those offices they can work with
    - What actions they can perform (e.g., push data to HOPE, validate records, etc.)

## Creating Groups with Permissions

### Step 1: Create a Group

Navigate to:
```
Admin › Authentication and Authorization › Groups
```

Click **[Add Group]** and give it a descriptive name (e.g., "Data Collectors", "Validators", "Managers").

### Step 2: Assign Permissions to the Group

Select the appropriate permissions from the available list. See the [Available Permissions](#available-permissions) section below for details on each permission.

## Assigning User Roles

Navigate to:
```
Admin › COUNTRY WORKSPACE › User roles
```

### Required Fields

- **User** - Select the user to grant permissions to
- **Country Office** - Select the office this role applies to
- **Group** - Select the group with the permissions you want to grant

### Optional Fields

- **Programme** - If left empty, the user will have permissions for **all programs** within the selected office. If a program is selected, permissions apply only to that specific program.
- **Expires** - If not set, permissions **never expire**. Set a date to create temporary access.

### Example Scenarios

**Grant office-wide access:**
- User: john.doe
- Country Office: Afghanistan
- Group: Data Validators
- Programme: (empty)

Result: John can validate data for all programs in Afghanistan office.

**Grant program-specific access:**
- User: jane.smith
- Country Office: Ukraine
- Group: Data Collectors
- Programme: Cash Transfer Program
- Expires: 2025-12-31

Result: Jane can collect data only for the Cash Transfer Program in Ukraine office until December 31, 2025.

## Available Permissions

### Programme Permissions

- **`workspaces.import_program_data`** - Can Import beneficiaries

    Allows users to import beneficiary data (Households and Individuals) into the program from various sources (Kobo, Aurora, XLS).

### Beneficiary (Household/Individual) Permissions

- **`workspaces.validate_beneficiary`** - Can validate Beneficiary Records

    Allows users to run validation checks on household and individual records to ensure data quality.

- **`workspaces.mass_update_beneficiary`** - Can Mass update Beneficiary Records

    Allows users to perform bulk field updates on multiple records at once using the mass update action.

- **`workspaces.regex_update_beneficiary`** - Can RegEx update Beneficiary Records

    Allows users to update fields using regular expressions for pattern-based replacements.

- **`workspaces.export_beneficiary`** - Can Export Beneficiary Records

    Allows users to export records to .xlsx files for offline bulk editing and reimport.

- **`workspaces.push_beneficiary_to_hope`** - Can Push Beneficiary Records To HOPE core

    Allows users to push validated beneficiary data to the HOPE core system. This is a critical permission as it affects production data.

- **`workspaces.calculate_checksum`** - Can calculate checksum for Beneficiary Records

    Allows users to calculate checksums for data integrity verification.

### Job Permissions

- **`country_workspace.debug_job`** - Can debug background jobs

    Allows users to access debugging information for asynchronous background jobs and tasks.
