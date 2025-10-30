# Constance Configuration

Constance variables are dynamic configuration settings that can be modified through the admin interface without requiring code changes or system restarts.

## Accessing Constance Configuration

To configure constance variables, navigate to the admin interface and go to:
```
Admin › Constance › Config
```

All configuration variables are organized into logical sections for easy management.

---

## Configuration Variables by Category

### New User Options

- **`NEW_USER_IS_STAFF`** (boolean, default: `False`)

    If True, new users will automatically have access to the admin panel (based on their assigned permissions).

- **`NEW_USER_DEFAULT_GROUP`** (group selection)

    Default group to assign to any new user.

### Cache

- **`CACHE_TIMEOUT`** (integer, default: `86400`)

    Cache Redis TTL (Time To Live) in seconds.

- **`CACHE_BY_VERSION`** (boolean, default: `False`)

    Invalidate cache on CW version change.

- **`KOBO_CACHE_TTL`** (integer, default: `86400`)

    Kobo data cache TTL in seconds. This is used during import from Kobo.

### Remote System Tokens

These settings configure connections to external systems (Aurora, HOPE, Kobo, Mailjet).

- **`AURORA_API_TOKEN`** (write-only)

    Aurora API Access Token for authenticating with the Aurora system.

- **`AURORA_API_URL`** (string)

    Aurora API Server address.

- **`HOPE_API_TOKEN`** (write-only)

    HOPE API Access Token for authenticating with the HOPE system.

- **`HOPE_API_URL`** (string)

    HOPE API Server address.

- **`KOBO_API_TOKEN`** (write-only)

    Kobo API Access Token for authenticating with the Kobo system.

- **`KOBO_MASTER_API_TOKEN`** (write-only)

    Kobo API Master Access Token. Used to access data under the specific project view

- **`KOBO_PROJECT_VIEW_ID`** (string)

    Kobo Project View ID. Used to access data under the specific project view

- **`KOBO_KF_URL`** (string)

    Kobo Server address.

- **`MAILJET_API_KEY`** (string)

    Mailjet API key for email services.

- **`MAILJET_SECRET_KEY`** (write-only)

    Mailjet secret key for email services.

### Data Consistency

- **`CONCURRENCY_GUARD`** (boolean, default: `True`)

    Prevent updates if data has changed after export. When enabled, the system will reject updates to records that were modified after they were exported. This helps maintain data consistency and prevents accidental overwrites of newer information.

---

## Security Notes

Sensitive configuration values (tokens, secret keys) use write-only fields and are masked in the admin interface. Default values for these fields are displayed as `***` to protect security credentials.
