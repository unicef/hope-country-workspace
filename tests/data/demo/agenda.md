# Scenario: HOPE Country Workspace (HCW) — end-to-end demo (configure → import → validate → push)

> Goal: demonstrate the full workflow in the application UI and admin UI: configure Constance and Program Data Checkers (Household/Individual), import beneficiary data (XLSX/KOBO), run validations with the configured Data Checkers, and push to HOPE Core.

---

## 0) Prerequisites

- User with role `Analyst`.
- User with role `Superuser` (for admin) or `Staff` with required permissions.
- Valid tokens with correct scopes (HOPE: read/write; KOBO: read).
- Celery workers are running.
- Redis is reachable for backend and Celery.

---

## 1) Configure (admin UI)

Navigation: `Home › Constance › Config`

Set the following:

    HOPE_API_URL = <your_hope_url>
    HOPE_API_TOKEN = <your_token>
    KOBO_KF_URL = <your_kobo_url>
    KOBO_MASTER_API_TOKEN = <your_token>
    KOBO_API_TOKEN = <your_token>
    KOBO_PROJECT_VIEW_ID = <your_project_id>
    MAILJET_API_KEY = <your_mailjet_key>
    MAILJET_SECRET_KEY = <your_mailjet_secret>

---

## 2) Synchronize reference data (admin UI)

**Scope:** `Offices`, `Beneficiary Groups`, `Programmes`, `Countries`, `Area Types`, `Areas`.
**Navigation:** `Home › Country Workspace › <specific model>`

**Sync modes**
- **Full sync** — <kbd>SYNC</kbd>; runs **asynchronously**. Track in `Home › Country Workspace › Async Jobs`.
- **Delta sync** — <kbd>SYNC DELTA</kbd>; runs **synchronously** and pulls **new/updated** only. Result message shown on the page.

**Cascade**
- Starting from **Offices** also syncs **Beneficiary Groups** and **Programmes**.
- Starting from **Countries** also syncs **Area Types** and **Areas**.

**Flex fields**
- To refresh values sourced from HOPE Core: `Home › Country Workspace › Sync logs` → <kbd>SYNC FLEX FIELDS</kbd>.

---

## 3) Configure data checkers (admin UI)

**What it is**:

Data Checkers define validation for beneficiary data. A Program references a **Household checker**  and an **Individual checker** (for HH+Individuals programs) and an **People checker** (for People programs). Checkers are composed from **Fieldsets** of **Flex Fields** (typed by **Field Definitions**). Data Checkers must match the data structure expected by HOPE Core.

**Where to configure (admin)**
- `Flex Fields › Field Definitions` — types/constraints; in the change view you have buttons <kbd>Test</kbd> and <kbd>Configure</kbd>.
- `Flex Fields › Flex Fields` — create fields and bind definitions; change view includes <kbd>Test</kbd>.
- `Flex Fields › Fieldsets` — group fields; **may extend** other fieldsets; button **Create from content type**.
- `Data Checkers` — create a checker and attach fieldsets; change view has <kbd>Test</kbd>, <kbd>Create XLS Importer</kbd> (build a template from checker fields), <kbd>Validate</kbd> (check a file), and <kbd>Inspect</kbd>.

**Fieldsets & grouping**
A fieldset can **extend** another fieldset (inherits its fields). Each fieldset has a string **Group** (display cluster). When adding a fieldset to a checker, you can set a **Prefix** so all fields from that fieldset are namespaced; you can also **override** the fieldset’s Group for this checker by filling **Group** on the member and toggling **Override group default value** = `True`.

**How to build a checker**
Attach **Fieldsets** to the **Data Checker**. Optionally set **Prefix**, **Order**, **Group**; toggle **Override group default value** to replace the fieldset’s Group for this checker.

The same fieldset may be attached more than once **with different prefixes**; duplicates with the same **checker + fieldset + prefix** are not allowed.

---

## 4) Import data (application UI & admin)

**Before you import** — on the **Program** page, ensure these are set: *Beneficiary validator, Household checker, Individual checker.*

**What it does**
Imports domain records for the current **Office + Program** — either **Households + Individuals** or **Individuals-only (“People”)** depending on the **Beneficiary Group**:
- **HH + Individuals** when `BeneficiaryGroup.master_detail = True`.
- **People-only** when `BeneficiaryGroup.master_detail = False` *(e.g., Social Workers)* — no Households are created, only **People** are created.

**How to import (application UI)**
1) Choose **Office** and **Program**.
2) Click **“Import data”**.
3) Pick a source.

**Runs & tracking**
- Each import runs as an **Async Job**. Job status and outputs (counts, warnings, row-level errors) appear under **Async Jobs** for the current **Office + Program**, or globally in the admin panel at `Home › Country Workspace › Async Jobs`.
- Each import creates a **Batch** (container of **all rows processed in that run**) scoped to **Office + Program + Source**. View in the application UI under **Batches** (admin: `Home › Country Workspace › Batches`).
- **Automatic field mapping (all sources):** **MappingImporter** rules linked to the selected **data checker** are applied during import (admin: `Home › Country Workspace › Mapping Importers`).

**Sources**

- **XLSX**
  - Use for demo: `tests/data/*.xlsx`.
  - **Validate mode (summary):**
    - *Skip validation — import data as is* (validate later in UI).
    - *Prevent import if data is not valid against data checker* (validates during import; blocks on errors; emails annotated copy).
    - *Prevent import if data is invalid AND fail if an alien field is found* (as above + strict alien-field check).
  - If errors occur in modes 2 or 3, an annotated copy of the XLSX with error notes is emailed to the user who initiated the import.

- **KOBO**
  - Prerequisite: the selected **Office** has a **KOBO country code** set (admin → **Office**).
  - Use for demo: Office **DRC**, project **“Questionnaire GVB - HH - ECHO”**.
  - Flow: select **Project ID** → <kbd>Import</kbd> → runs as an **Async Job**.

**Post-import**
Review **Households** / **Individuals** in the UI to verify created records.

---

## 5) Validation (application UI, not admin)

**What it is**
Validation checks Household/Individual fields against the Program’s configured **Data Checkers**.

**When it runs**
- **During import** — if **Validate mode** is set to validate-on-import.
- **On demand (post-import)** — manual run from the application UI.

**How to run (application UI)**
1) Choose **Office** and **Program**.
2) Open the **Households** tab (or **Individuals (People)** for People-only programs).
3) To validate **all records** of the Program: click **Validate Programme** — this creates an **asynchronous job**.
4) To validate **selected records** from the list of beneficiaries: use **Actions → Validate selected records** — this creates an **asynchronous job**.
5) To validate **a single record**: select the record → click **Validate** — this runs **synchronously**.

**Status & results**
- Bulk validations (via **Validate Programme**) appear under **Async Jobs** for the current **Office + Program**, or globally in `Home › Country Workspace › Async Jobs`.
- Single-record validations show results immediately on the record page.
- In list views, the **Is Valid** status is visible; on a record’s detail page, you can see full validation error details.

---

## 6) Actions (application UI, not admin)

Bulk actions for beneficiaries in the **Households** or **Individuals (People)** tabs.

**Common flow & tracking**
- Select records in the list → choose an **Action**.
- Most actions create an **asynchronous job**. Monitor progress under **Async Jobs** (for the current **Office + Program**, or globally in the admin at `Home › Country Workspace › Async Jobs`).

---

### 6.1) Export records as XLSX (for bulk updates)

1) Select records → **Actions → Export records as XLSX**.
2) On the next screen, **select the columns you want to update** → <kbd>Export</kbd>.
3) An **async job** runs; the resulting XLSX is **emailed** to you.
4) Edit the file locally and upload it back via the Program page button <kbd>Update Records</kbd>.

**Concurrency guard (Constance)**
`CONCURRENCY_GUARD`: *Prevent updates if data has changed after export.*
When enabled, updates are rejected for any record that was modified after the export, to avoid overwriting fresher data.

---

### 6.2) Mass update record fields

1) Select records → **Actions → Mass update record fields**.
2) Choose **fields**, pick an **update method**, and set **values**.
3) Optional: **create missing fields** — creates absent (flex) fields on the selected records.
4) <kbd>Apply</kbd> → an **async job** runs.

---

### 6.3) Update fields using Regex

1) Select records → **Actions → Update fields using Regex**.
2) Choose **field**, enter **regex** and **subst** (replacement).
3) <kbd>Preview</kbd> — shows old vs new value.
4) If correct, <kbd>Apply</kbd> → an **async job** runs.

---

**Also available**
- **Validate selected records** — see Section 5.
- **Push to HOPE Core** — see Section 7.

---

## 7) Push to HOPE Core (application UI & admin panel)

**Before you push** — on the **Program** page, ensure these are set: *Beneficiary validator, Household checker, Individual checker, Serializer.*

**What it does**
Pushes selected domain records to HOPE Core for the current **Office + Program**.

**How to push (application UI)**
1) Choose **Office** and **Program**.
2) Open the **Households** tab (for HH + Individuals programs) or **Individuals (People)** tab (for People-only programs).
3) Select records → **Actions** → <kbd>Push to HOPE Core</kbd>.

**Runs & tracking**
- Each push creates a **Registration Data Push (RDP)** that groups the records included in that run.
- RDP **status**: `Pending`, `Success`, `Failure`. You **cannot** re-push records already included in a `Pending` RDP; you **can** re-push records from a `Failure` RDP.
- View RDPs in the application UI under **Registration Data Pushes**, or in the admin at `Home › Country Workspace › Registration Data Pushes` (admin shows **all** RDPs and provides a **Records** action to inspect included items).
- Job progress and output are available under **Async Jobs**.

**Post-push behavior**
On successful push, affected beneficiaries are flagged `removed = True`. They no longer appear in UI lists, but remain accessible in the admin.

---
