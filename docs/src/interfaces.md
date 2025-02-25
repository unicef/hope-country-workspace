# Hope Workspace Interfaces

Hope Workspace provides two interfaces for different roles:

### **Collector Interface**

The primary interface for data collection and processing, offering an enhanced user experience with additional workspace features.



#### Households Page / Individuals Page

Displays a list of households and individuals related to the selected program, with filtering options and the ability to validate the entire program.

When selecting an item, you can view or edit the imported data by columns, make necessary corrections, and validate the data for the chosen entry to detect any potential issues.

---

#### Program page

Provides complete information about the selected program, along with available actions accessible via buttons, including:

??? abstract "[Household Columns]"
    ##### **[Household Columns]**
    Allows the user to configure mandatory columns for the Household Checker, which will be used with Household records.

??? abstract "[Individual Columns]"
    ##### **[Individual Columns]**
    Allows the user to configure mandatory columns for the Individual Checker, which will be used with Individual records.

??? abstract "[Update Records]"
    ##### **[Update Records]**
    Imports column updates from a file for either Household or Individual records.

??? abstract "[Import data]"
    ##### **[Import data]**
    Import Household and Individual data from different sources to ensure seamless integration into the system. This process supports multiple data formats and validation steps to maintain data consistency. For more details, refer to the [Import Data](import_data/index.md).

For convenience, the **Program** page includes a dedicated button, represented by a shield icon, allowing quick access to essential admin functions.

---

#### Batch page

Displays a list of batches. A batch is an entity that contains references to imported data sources for the selected program. The page includes filtering options, allowing users to refine the list. For a selected batch, you can view the imported records.

---
#### Jobs Page

Displays a list of asynchronous jobs with filtering options. For a selected job, you can perform various actions, such as *inspect*, *queue*, *revoke*, or *terminate* it.

---

###  **Admin Interface**
A standard Django admin panel used for managing diverse configurations, setting up flex fields, controlling user access, and synchronizing Unified Classifiers with the HOPE main system.

---

## Synchronize Unified Classifiers

**Unified Classifiers** are centralized reference data that categorize key elements essential for process unification, including *offices*, *programs*, and *registrations*.

To synchronize data in the admin interface, press the **[SYNC]** button for the corresponding classifier.
