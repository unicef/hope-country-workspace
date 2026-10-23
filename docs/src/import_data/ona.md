# INFORM / ONA Registration Data Import Connector

## Purpose

This connector adds INFORM / ONA as a Registration Data Import source for Country Workspace.

It pulls submissions from the ONA API, converts ONA JSON into Country Workspace household and individual import records, and reuses the existing Country Workspace import flow, including:

- `build_import_processor`
- `run_batch_postprocessing`
- optional validation jobs

It does not push data directly to HOPE.

## Configuration

The connector uses the following ONA / INFORM settings:

- `ONA_API_TOKEN` — ONA API access token.
- `ONA_API_URL` — ONA API server address.
- `ONA_APPROVED_FORMS` — JSON configuration of ONA / INFORM forms that are allowed for import.
- `ONA_IMPORT_TIMEBOX_MINUTES` — maximum number of minutes an import job processes submissions before scheduling a continuation for the same batch. The default is `30`; set to `0` to disable timeboxing.
- `ONA_HH_FIELDS_TO_IGNORE` — comma-separated default ONA household fields to ignore during data import. The default is empty.
- `ONA_IND_FIELDS_TO_IGNORE` — comma-separated default ONA individual fields to ignore during data import. The default is empty.

The default ONA API URL is:

```text
https://data.inform.unicef.org
```

For a form ID such as `9153`, the data endpoint is:

```text
https://data.inform.unicef.org/api/v1/data/9153
```

## Approved ONA / INFORM forms

ONA / INFORM imports are restricted by `ONA_APPROVED_FORMS`.

Users cannot manually enter an arbitrary ONA form ID. Approved forms are configured centrally and presented as controlled choices for the current Country Workspace office/programme.

Example:

```json
{
  "9153": {
    "label": "Yemen INFORM Registration",
    "programmes": ["IDP"],
    "offices": ["Yemen CO"]
  }
}
```

## Field mapping

ONA-specific transformation prepares the source data for the existing Country Workspace mapping importer rather than defining a separate per-import field mapping.

Nested ONA / ODK JSON is flattened into slash-separated source field names before mapping. For example:

```text
household/name
household/governorate
```

ONA / ODK system fields whose final field name starts with `_`, such as `_id`, `_uuid`, and `_submission_time`, are removed before the mapping importer processes the source data.

For master/detail forms, the configured repeat group is separated from the household source record and each repeat entry is processed as an individual source record.

## Resumable imports

ONA imports can be timeboxed using `ONA_IMPORT_TIMEBOX_MINUTES`.

When the timebox is reached:

- successfully committed submissions keep their persisted ONA cursor;
- the current batch remains in progress;
- a continuation job is queued for the same batch;
- post-processing, optional validation, batch completion, and the final import signal run only after the import is fully complete.

## Batch reprocessing

ONA household reprocessing preserves primary and alternate collector references and rebuilds household references using the same reference synchronization behavior used for Kobo imports.

## Main files

- `src/country_workspace/contrib/ona/client.py`
- `src/country_workspace/contrib/ona/forms.py`
- `src/country_workspace/contrib/ona/transformers.py`
- `src/country_workspace/contrib/ona/import_processing.py`
- `src/country_workspace/contrib/ona/exceptions.py`
- `src/country_workspace/contrib/ona/apps.py`

## Batch source

ONA is registered as:

```python
Batch.BatchSource.ONA
```
