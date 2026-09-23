# Images and documents

Image fields such as **Photo**, **Consent sign** and the document images of an Individual or Household keep their content outside the record itself. The record stores a reference to the picture, and Country Workspace resolves that reference when the picture is displayed or sent to another system.

This is why image fields behave differently from the other fields of a record, both when records are edited and when they are updated in bulk.

## Where images come from

Pictures reach a record through one of these paths:

* an **[XLSX import](data_import/sources/xlsx.md)**, where an image is anchored in the row of the beneficiary;
* a **[Kobo import](data_import/sources/kobo.md)**, where the attachment of a submission is downloaded during the import;
* **[Import pictures](data_import/picture_import.md)**, where a ZIP archive is matched against an existing Batch;
* a manual upload on the change form of a single Individual or Household.

## View an image

On the change form, each image field shows the current picture. Selecting it opens the full image in a new tab.

**View Raw Data** shows a thumbnail of each stored picture together with the identifier of the stored file, which is useful when reporting a problem with a specific image.

When an image field is configured as a column of the Individuals or Households list, the column shows a link to the picture instead of the stored value.

Pictures are served only to users who are allowed to view the record that owns them, in the same Country Office and Program. Knowing the identifier of a picture is not sufficient to open it.

## Replace or clear an image

Uploading a new file on the change form replaces the picture of that field. Clearing the field removes the picture from the record.

Earlier pictures of a record are retained, so **History** keeps showing the picture a field had before each change. Pictures are removed together with the Individual or Household that owns them.

Reprocessing a **[Batch](data_import/batches.md)** rebuilds the fields of each record from its stored source data, and the originally imported picture is restored with them. Pictures added through **[Import pictures](data_import/picture_import.md)** are not part of the source data and must be imported again after reprocessing.

## Bulk actions and exports

Image and document fields are excluded from the actions that change many fields at once, because a picture cannot be expressed as a cell value:

* **Mass update record fields**, **Update fields using RegEx**, **Concatenate field action** and **Parse name into components** do not offer them as a field to update;
* **Export records as .xlsx for bulk updates** leaves those columns out of the generated file, and a column matching an image field is ignored when the file is imported back, so an edited cell can never overwrite a picture.

When selecting the columns of a Program, image fields are marked with `[file]` so that they can be recognized before they are added to a list.

Use **[Import pictures](data_import/picture_import.md)** to add or replace pictures for many records at once.

## Troubleshooting

If an image field shows no picture, check the following in order:

* the record was imported without a picture for that field, which **View Raw Data** confirms;
* the Batch was reprocessed after pictures were added through **Import pictures**, in which case the pictures must be imported again;
* the picture was cleared on the change form, which **History** confirms.

A record whose picture cannot be resolved at all stops the job that needs it, such as a **[push to HOPE](rdp/push.md)** or a **[deduplication](rdp/deduplication.md)** run, instead of sending an incomplete record. Review the related background job for the affected record.
