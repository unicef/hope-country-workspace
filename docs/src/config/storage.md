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

Access it at runtime through Django's storages registry:

```python
from django.core.files.storage import storages

storage = storages["hope"]
storage.save(key, content_file)
storage.open(key, "rb")
storage.exists(key)
storage.delete(key)
```

Handle missing blobs with `azure.core.exceptions.ResourceNotFoundError` (and `FileNotFoundError` for local filesystem storage in tests).

!!! note "Blob keys, not file bytes"
    The database stores blob **keys/paths as plain strings**, not the file contents and not a `FileField`. Agree a key-prefix convention with HOPE core (for example `households/{pk}/photo.jpg`) so writes from different services do not collide.

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
