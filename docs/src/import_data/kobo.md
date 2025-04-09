# Import data from Kobo

[KoboToolbox](https://www.kobotoolbox.org/) is a set of tools for data collection. It allows user to create forms and
collect data.

---

### Prerequisites

KoboToolbox integration is configured with the following variables
```shell
KOBO_KF_URL
KOBO_MASTER_API_TOKEN
KOBO_PROJECT_VIEW_ID
KOBO_API_TOKEN
```

these are defined in the Constance configuration in the [Admin Interface](../interfaces.md#admin-interface):

```
Home › Constance › Config > Remote System Tokens
```

The variables control which data can be imported from KoboToolbox:

1. When variables below are set:
    ```shell
    KOBO_KF_URL
    KOBO_MASTER_API_TOKEN
    KOBO_PROJECT_VIEW_ID
    ```
   data from forms under specific project view can be imported
2. When variables below are set:
    ```shell
    KOBO_KF_URL
    KOBO_API_TOKEN
    ```
   data from forms of the specific user can be imported
---

### Processing

In the [Collector Interface](../interfaces.md#collector-interface), navigate to the **[Programmes]** menu item on the left, then click the
**[Import Data]** button and choose the **[Kobo]** tab. If you see the message below before you can import data

```text
Please set country iso code for office to use Kobo import
```

you have to set `Kobo country code` for the office you use in admin interface.

The Kobo import form contains following configuration parameters:

- **Batch Name** – a custom batch name if needed.

- **Project id** – a project view id KoboToolbox forms belong to.

- **Individual records field** - a prefix used in form to group individual data. All the individual data is grouped
under this key in JSON we get from KoboToolbox.

- **Check Before** – a flag to not import data on any data inconsistency.

- **Fail if Alien** – a flag to not import data if it contains unknown fields.

Once settings are configured, you can click **[Import]** to start import or click **[Close]** to cancel it.
