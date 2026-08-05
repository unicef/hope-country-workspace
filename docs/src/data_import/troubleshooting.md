# Troubleshooting imports

This page covers issues common to all data import sources. For problems specific to RDI, Aurora, or Kobo, see the relevant page under [Data sources](sources/index.md).

## The import job failed

Open the background job and review its error details.

Failure and retry behavior depend on the import source. Some sources roll back the imported records, while others preserve successfully processed records and continue from the last completed record.

See the troubleshooting section for the relevant [data source](sources/index.md).

## The Batch remains in Loading status

The import may still be running or continuing in another background job.

A Batch can also remain in **Loading** when processing fails before finalization. Review the related background jobs and the failure behavior described for the relevant data source.

## The Batch is empty or some records are missing

Check the source-specific import behavior and the related background jobs.

Aurora and Kobo imports are incremental and normally import only records that are newer than the last successfully imported record. RDI record selection depends on the workbook structure and configured identifier fields.

## Imported fields or values are unexpected

Review:

- the source-specific field preparation rules;
- the selected [Mapping Importers and Transformers](mapping_transformers.md);
- the current Program defaults and DataChecker configuration.

If the issue is caused by the processing configuration, correct it and [reprocess the Batch](batches.md#reprocessing).

## Validation results are missing

Import processing and validation run separately.

Check whether **[Validate after import](index.md#validation-after-import)** was enabled for the import. If it was disabled, validate the affected records separately.

A Batch can become **Complete** while its validation jobs are still running. Review the background validation jobs and wait for them to finish.

## Records contain validation errors

Open the Batch and review the errors on the affected records.

Correct the processing configuration and reprocess the Batch, or correct the affected records and validate them again.

## Reprocessing did not apply changes from the source

Reprocessing uses the source data stored with the existing Batch. It does not reload changes made later in the original workbook, Aurora Registration, or Kobo project.

For RDI, start a new import using the updated workbook. Aurora and Kobo do not automatically reload changes to records or submissions that were already imported; see the troubleshooting section for the relevant data source.
