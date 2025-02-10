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

2. Additionally, select the appropriate **checkers** for both **Households** and **Individuals** corresponding to the specific program.

---

### Processing

To begin, in the [Collector Interface](../interfaces.md#collector-interface), navigate to the menu

    Program

menu, then press the **[Import Data]** button and select the **[Aurora]** tab. Here, you can configure the import settings:

- **Batch Name** – Specify a custom batch name if needed.

By default, will be used: *<"Batch " + the current datetime>*

- **Registration** – Select the specific Aurora registration to import. If needed, [synchronize](../interfaces.md#synchronize-unified-classifiers) registrations before proceeding.
- **Check Before** – Enable this option to prevent the import if errors are detected.
- **Household Name Column** – Specify which Individual's column contains the Household's name.

By default, this is set to *family_name*.

- **Fail if Alien** – Enable this option to fail the import if any unexpected fields (not defined in the validator) are found.

Once all settings are correctly configured, press **[Import]** to proceed or **[Close]** to cancel. After initiating the import, you will be redirected to the **Jobs** page, where you can track the progress and details of the import job.
