# Data Synchronization

Data synchronization ensures that information from external sources is properly imported and kept up to date within the Country Workspace.

## Sync Types

There are two types of sync in Country Workspace:

1. **Full Sync (Sync)** - Syncs everything from the source, no matter what has already been synced. This is run as a Celery task as it might be time consuming.

2. **Incremental Sync (Sync Delta)** - Checks the last sync date and only syncs records that were updated since then. It is recommended to use Sync Delta after the first sync if there is no specific reason not to.

---

## Sync from HOPE

There are several entities that need to be synced from HOPE, including: Offices, Beneficiary groups, Programmes, Countries, Admin area types, Admin areas, and lookups for some of the flex fields.

### Step 1: Sync Offices, Beneficiary Groups, and Programmes

Navigate to:
```
Admin › COUNTRY WORKSPACE › Offices
```

Click the **[Sync]** button. This will schedule a Celery task to sync all the relevant data from HOPE.

### Step 2: Sync Countries, Admin Area Types, and Admin Areas

Navigate to:
```
Admin › COUNTRY WORKSPACE › Countries
```

Click the **[Sync]** button. This will schedule a Celery task to sync all the relevant records from HOPE.

### Step 3: Sync Flex Fields Lookups

Navigate to:
```
Admin › COUNTRY WORKSPACE › Sync logs
```

Click the **[Sync flex fields]** button to sync all the field lookups. The **Last update date** field can be checked to see when it was last updated.

### Syncing Individual Entities

You can sync entities individually as well. For example, to sync only programmes:

Navigate to:
```
Admin › COUNTRY WORKSPACE › Programmes
```

Then perform a full or incremental sync.

---

## Sync from Aurora

To start importing data from Aurora, you first need to sync registrations from Aurora.

Navigate to:
```
Admin › CONTRIBUTED SERVICE | AURORA › Registrations
```

Click the **[Sync]** button to sync Aurora registrations.
