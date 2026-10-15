\# INFORM / ONA Registration Data Import Connector



\## Purpose


## Configuration

The connector uses Constance/env settings for credentials and endpoint configuration:

- `ONA_API_TOKEN`
- `ONA_API_URL`

Default `ONA_API_URL`:

```text
https://data.inform.unicef.org

For an INFORM form ID such as 9153, the connector calls:

https://data.inform.unicef.org/api/v1/data/9153


## Step 2 — Confirm docs updated

```bash
grep -Rni "data.inform.unicef.org\|ONA_API_URL\|ONA_API_TOKEN" docs/src/import_data/ona.md
This connector adds INFORM / ONA as a Registration Data Import source for Country Workspace.



The connector pulls submissions from the ONA API, maps ONA JSON fields into Country Workspace household/individual records, and reuses the existing import flow:



\- `build\_import\_processor`

\- `run\_batch\_postprocessing`

\- optional validation jobs



It does not push anything directly to HOPE.


### Approved ONA / INFORM forms

ONA / INFORM imports are restricted by `ONA_APPROVED_FORMS`.

The import form does not allow users to manually enter any arbitrary ONA form ID. Instead, approved forms are configured and shown as controlled choices for the current Country Workspace office/programme.

Example configuration:

```json
{
  "9153": {
    "label": "Yemen INFORM Registration",
    "programmes": ["IDP"],
    "offices": ["Yemen CO"]
  }
}



\## Main files



\- `src/country\_workspace/contrib/ona/client.py`

\- `src/country\_workspace/contrib/ona/transformers.py`

\- `src/country\_workspace/contrib/ona/import\_processing.py`

\- `src/country\_workspace/contrib/ona/exceptions.py`

\- `src/country\_workspace/contrib/ona/apps.py`



\## Batch source



ONA is registered as a batch source:



```python

Batch.BatchSource.ONA

