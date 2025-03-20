# Import data from Aurora

[Aurora](https://unicef.github.io/hope-aurora/) is the official online registration tool for HOPE. Developed in 2022 for the Ukraine emergency, it quickly became the de-facto standard for online registration in almost all the countries served online by UNICEF.

---

### Prerequisites

1. Before using the system, ensure that the following variables
```
AURORA_API_URL
AURORA_API_TOKEN
```
are defined in the Constance configuration within the [Admin Interface](../interfaces.md#admin-interface):
```
Home › Constance › Config > Remote System Tokens
```

2. Additionally, select the appropriate **checkers** for both **Households** and **Individuals** corresponding to the specific program within the [Collector Interface](../interfaces.md#collector-interface):
```
Programme
```

---

### Processing

To begin, in the [Collector Interface](../interfaces.md#collector-interface), navigate to the menu
```
Programme
```
menu, then press the **[Import Data]** button and select the **[Aurora]** tab. Here, you can configure the import settings:

- **Batch Name** – Specify a custom batch name if needed.

By default, will be used: *<"Batch " + the current datetime>*

- **Registration** – Select the specific Aurora registration to import. If needed, [synchronize](../interfaces.md#synchronize-unified-classifiers) unified classifiers before proceeding.

- **Household column prefix** - A string added at the beginning of column names to indicate household-related data. It can appear in various forms (e.g., "household_" or "household-info") and is used to group these columns.

- **Individuals column prefix** - A string added at the beginning of column names to indicate individual-related data. It can appear in various forms (e.g., "individual-details_" or "personas_") and is used to group these columns.

- **Household label column** – Specify which Individual's column should be used as label for the household.

By default, this is set to *family_name*.

- **Check Before** – Enable this option to prevent the import if errors are detected.

- **Fail if Alien** – Enable this option to fail the import if any unexpected fields (not defined in the validator) are found.

Once all settings are correctly configured, press **[Import]** to proceed or **[Close]** to cancel. After initiating the import, you will be redirected to the **Jobs** page, where you can track the progress and details of the import job.
