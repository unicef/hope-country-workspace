# Program

A **Program** represents a campaign or intervention targeting a specific group of beneficiaries for a specific operational need, for example `Cash for nutrition`.

## Program context

In Country Workspace, users first select an **Office** and a **Program**.

The selected Program becomes the working context for beneficiary data. It affects how records are imported, reviewed, validated, reprocessed, and later prepared for data push operations.

Users can open import from the Program page or from related Household / Individual pages, but the import always runs in the context of the selected Program.

## What the Program defines

The selected Program defines the main setup used for beneficiary import and review:

* **Beneficiary structure**: whether users work with Households and Individuals, or with people-only Individual records.
* **Validators**: high-level checks for beneficiary records. For household-based Programs, the default beneficiary validator should usually be **FullHouseholdValidator**. It checks that the Household has a Head, has a Primary Collector, does not use the same person as both Primary and Alternate Collector, and that the Head belongs to the Household.
* **DataCheckers**: expected Household and Individual fields, grouping, and validation rules. They are based on [DataChecker configuration](../data_validation/datachecker_configuration.md).
* **Columns**: fields shown when users review imported records. Columns do not change imported data.
* **Alien Columns to Ignore**: known extra source fields that should not block validation when alien validation is enabled.
* **Serializer**: prepares already imported beneficiary data for later integrations, such as sending records to HOPE Core.
* **Deduplication configuration**: displays biometric deduplication settings when they are available. If settings are not available, the section may show `N/A`.

[Mappings](mapping_transformers.md#mapping-importers) are managed from the Country Workspace interface. [Transformers](mapping_transformers.md#transformers) and serializers are configured in the main Django admin and then used in the [import](import.md) or [Batch reprocessing](batches.md#reprocessing) flow.

## Country Workspace interface

In this documentation, **Country Workspace interface** means the analyst / collector workspace where users select an Office and Program and work with beneficiary data.

This is different from the main Django admin, which is used for technical configuration.

Open Country Workspace and select the required **Office** and **Program** from the top navigation bar.

The Country Workspace menu provides access to related sections, such as:

* **Households** and **Individuals**, or only **Individuals** for people-only Programs;
* [**Batches**](batches.md);
* [**Mappings**](mapping_transformers.md#mapping-importers);
* **Registration Data Pushes**;
* **Async Jobs**.

## Import from a Program

Use **Import Data** to start a beneficiary import in the selected Program context.

For the full import flow and supported sources, see [Beneficiary import](import.md).

## Before importing

Before starting an import, check that:

* the correct Office and Program are selected;
* the Program uses the expected beneficiary structure: Households with Individuals, or people-only Individuals;
* the required Validators and [DataCheckers](../data_validation/datachecker_configuration.md) are configured;
* review columns are configured;
* known Alien Columns are added to ignore lists, if needed;
* required [Mappings](mapping_transformers.md#mapping-importers) exist in the Country Workspace interface;
* required [Transformers](mapping_transformers.md#transformers) exist in the main Django admin, if source values need transformation;
* the correct serializer is selected for the Program, if imported records will later be sent to HOPE Core or another integration.

After import, review the created [Batch](batches.md), imported records, validation results, and related **Async Jobs**.
