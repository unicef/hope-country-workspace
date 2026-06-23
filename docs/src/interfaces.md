# Country Workspace interface

Country Workspace has two main interfaces used for different types of work:

* the **Country Workspace interface**, used by analysts and collectors to work with beneficiary data;
* the **main Django admin**, used for technical configuration and system administration.

## Country Workspace interface

The **Country Workspace interface** is the main working area for beneficiary data.

Users select an **Office** and a **Program**, then work in the context of that selected Program.

This interface is used for operational tasks such as beneficiary review, [import](data_import/import.md), [Batch](data_import/batches.md) review, validation results, mappings, and data push follow-up.

For import-related work, the selected [Program](data_import/program.md) defines the working context: beneficiary structure, validation setup, review columns, Alien Columns, and later processing options.

## Main Django admin

The **main Django admin** is used for technical configuration.

It is used to configure objects that support Country Workspace processes, such as:

* [DataChecker configuration](data_validation/datachecker_configuration.md);
* Flex Fields and Fieldsets;
* [Transformers](data_import/mapping_transformers.md#transformers);
* serializers;
* user access and permissions;
* system-level reference data and synchronization settings.

Most users working with beneficiary data do not need to use the main Django admin directly.

## How the interfaces work together

Some objects are configured in the main Django admin and then used in the Country Workspace interface.

For example:

* DataCheckers are configured in the main Django admin and assigned to a Program;
* Mappings are managed in the Country Workspace interface;
* Transformers and serializers are configured in the main Django admin and selected or used during import, reprocessing, or later integrations.

This separation keeps operational work focused in the Country Workspace interface while keeping technical setup in the main Django admin.

## Unified Classifiers

Unified Classifiers are shared reference data synchronized with the HOPE main system.

They may include offices, programs, registrations, and other reference data required by Country Workspace.

When classifier data is missing or outdated, it should be synchronized from the main Django admin by a user with the required permissions.
