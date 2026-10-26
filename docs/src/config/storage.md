# Blob Storage

Country Workspace stores files through Django's `STORAGES` dict, configured via `django-smart-env`. Each backend is selected from an environment variable that encodes the backend class and its options as a URL-like string:

```
<backend.dotted.path>?<option>=<value>&<option>=<value>
```

| Env var | STORAGES alias | Purpose |
|---|---|---|
| `FILE_STORAGE_DEFAULT` | `default` | Local scratch / default storage |
| `FILE_STORAGE_MEDIA` | `media` | App media uploads |
| `FILE_STORAGE_STATIC` | `staticfiles` | Static assets |
| `FILE_STORAGE_HOPE` | `hope` | Shared HOPE blob container (read-write) |

## Shared HOPE storage (`FILE_STORAGE_HOPE`)

`FILE_STORAGE_HOPE` points at the **shared HOPE Azure blob container**, which is used across multiple HOPE services. Country Workspace needs **read-write** access to it (unlike the dedup-engine, which is read-only).

Access it at runtime through the lazily-resolved storage singletons in `country_workspace.storages`, not Django's `storages[...]` registry directly:

```python
from country_workspace.storages import HOPE_STORAGE

HOPE_STORAGE.save(key, content_file)
HOPE_STORAGE.open(key, "rb")
HOPE_STORAGE.exists(key)
HOPE_STORAGE.delete(key)
```

`MEDIA_STORAGE` (same module) wraps `STORAGES["media"]` the same way. Both are `SimpleLazyObject`s that resolve `settings.STORAGES` on first use; the deploy check below guarantees the backend is valid and reachable before anything saves to it.

Handle missing blobs with `azure.core.exceptions.ResourceNotFoundError` (and `FileNotFoundError` for local filesystem storage in tests).

!!! note "Deterministic blob keys"
    A record's picture can be stored either inline in `flex_fields` as a base64 data-URI (legacy) or offloaded to the `FlexFieldFile` table and referenced from `flex_fields` by a `flexfile:<uuid>` string (see [Flex field files](#flex-field-files) below). `services.hope_blob.sync_record_blobs` resolves either shape transparently before syncing, and the DB only keeps a per-field content hash in `blob_hashes` to avoid re-uploading unchanged content. Blob paths are recomputed on each transfer via `hope_blob_key()` and substituted into outgoing payloads:

    ```
    {office.code}/{program.code}/CW_{entity}_{pk}_{name}.png
    ```

    - `entity`: `ind` (Individual) or `hh` (Household)
    - `name`: the raw `flex_fields` image field key (e.g. `photo`, `national_id_image`)

    Example: `AFG/CP-2024/CW_ind_12345_photo.png`

## Flex field files

File-typed flex fields (images, document scans) can store their payload in the `FlexFieldFile` table instead of inline in `flex_fields`. A `FlexFieldFile` row is owned by the `Household` or `Individual` it belongs to (via a generic relation) and holds the raw `content`, `mimetype`, `size`, `checksum` and original filename. The owning record's `flex_fields` value becomes a `flexfile:<uuid>` reference instead of a base64 data-URI.

Rows are append-only: replacing or clearing a field never deletes the previous row, since `raw_data` and history events may still point at it. Rows are only removed together with the record that owns them.

New uploads (manual edits, [Import pictures](../data_import/picture_import.md), imports from sources using `FlexImageField`) are written straight to this table. Databases upgraded from a release that stored files inline can be migrated with the `migrate_flex_files` management command:

```bash
python manage.py migrate_flex_files --model all
```

It scans `Household`/`Individual` records for inline base64 values, writes one `FlexFieldFile` row per distinct payload, and rewrites `flex_fields`/`raw_data` to reference it. The command is idempotent and resumable (`--start-pk`, `--limit`), supports `--dry-run`, and can convert files back inline with `--reverse` (handy for rolling back). Run it after `migrate`, while holding the `lock:migrate_flex_files` cache lock (acquired automatically; skip with `--no-lock` only for a single-writer maintenance window).

## Environment values

### Production / staging (real Azure)

```
FILE_STORAGE_HOPE="storages.backends.azure_storage.AzureStorage?account_name=<account>&account_key=<key>&azure_container=hope&overwrite_files=True"
```

or with a connection string:

```
FILE_STORAGE_HOPE="storages.backends.azure_storage.AzureStorage?azure_container=hope&overwrite_files=True&connection_string=<conn_str>"
```

- Grant **read + write** IAM permissions on the `hope` container.
- `overwrite_files=True` is **required**: blob sync writes deterministic keys and relies on `save()` overwriting in place. The deploy check (`E004`) fails without it.
- Keep credentials in a vault / K8s secrets. Never commit them and never put them in Constance (they must not be admin-editable).

### Local development (Azurite)

`compose.yaml` runs an `azurite` service and sets `FILE_STORAGE_HOPE` to the Azurite emulator connection string with `azure_container=hope`. It also sets `INIT_HOPE_STORAGE=1`, which makes the entrypoint run the `init_hope_storage` management command on startup to create the container idempotently. This flag is unset in production (where the container is provisioned out-of-band).

### Tests

`tests/conftest.py` overrides `FILE_STORAGE_HOPE` with a local `FileSystemStorage` so tests never touch Azure.

## Deploy check

A deploy-time system check (`country_workspace/checks.py`, run via `django-admin check --deploy`) validates that the `hope`, `staticfiles`, and `media` storages resolve, and, when backed by Azure, that credentials and the container are reachable, and that the `hope` storage is configured with `overwrite_files=True`.
