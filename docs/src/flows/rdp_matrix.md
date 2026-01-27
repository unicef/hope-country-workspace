### Status meaning (glossary)

- **`Rdp.PushStatus`** — the **global RDP lifecycle status** for the “push to HOPE Core” workflow. It is the primary outcome indicator for the whole RDP process.
- **`Rdp.DedupRunState`** — the **internal deduplication lifecycle** maintained locally (not started / in progress / accepted after a successful push).

- **`dedup_engine_state`** is a **read-only admin display field** that summarizes the current deduplication status.

---

## Table A — Button visibility

| PushStatus | Deduplicate visible | Push visible |
|---|---:|---:|
| **PENDING** | True | True |
| **FAILURE** | False | False |
| **SUCCESS** | False | False |
| **CANCELLED** | False | False |

---

## Table B — Enabled state + `dedup_engine_state` (ordered by real lifecycle)

| PushStatus | DedupRunState | Remote DedupEngine status | Deduplicate enabled | Push enabled | `dedup_engine_state` |
|---|---|---|---:|---:|---|
| **PENDING** | NOT_RUN | *(not checked)* | True | False | `"N/A"` |
| **PENDING** | IN_PROGRESS | **PENDING** | False | False | `"pending"` |
| **PENDING** | IN_PROGRESS | **STARTED** | False | False | `"started"` |
| **PENDING** | IN_PROGRESS | **SUCCESS** | False | True | `"success with findings=<n>"` |
| **PENDING** | IN_PROGRESS | **FAILURE** | True | False | `"failure"` |
| **PENDING** | IN_PROGRESS | **NOT_SCHEDULED** | True | False | `"not_scheduled"` |
| **PENDING** | IN_PROGRESS | **REVOKED** | True | False | `"revoked"` |
| **PENDING** | IN_PROGRESS | **UNKNOWN** | True | False | `"unknown"` |
| **FAILURE** | *(any)* | *(not checked)* | False | False | `"N/A"` |
| **SUCCESS** | *(any)* | *(not checked)* | False | False | `"N/A"` |
| **CANCELLED** | *(any)* | *(not checked)* | False | False | `"N/A"` |

Notes:
- Rows marked “not checked” mean **no DedupEngine call is performed** for that state.
- `Remote status = UNKNOWN` covers both a real `UNKNOWN` response and any exception while fetching status.
