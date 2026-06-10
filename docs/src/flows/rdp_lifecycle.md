## RDP state flow

```mermaid
stateDiagram-v2
    [*] --> PENDING: Create RDP or Clone child

    PENDING --> PENDING: Dedup via DE REST
    PENDING --> FAILURE: Push failed
    PENDING --> PUSHED: Push succeeded
    PENDING --> REJECTED: Reject DS
    PENDING --> REJECTED: Clone replaces PENDING source

    PUSHED --> MERGED: HOPE callback MERGED
    PUSHED --> REJECTED: HOPE callback REJECTED
    PUSHED --> REJECTED: Admin Reset job applies REJECTED finalization
    PUSHED --> PUSHED: Callback or Reset job failed

    FAILURE --> [*]: Final failed
    REJECTED --> [*]: Final rejected
    MERGED --> [*]: Final merged

    note right of PENDING
        Local processing status.<br>
        Deduplication may create or process a DE set.
        RDP remains PENDING after dedup success or DE error.
    end note

    note right of FAILURE
        Push workflow failed.<br>
        RDP was not successfully handed off to HOPE Core.
    end note

    note right of PUSHED
        CW completed the HOPE RDI push successfully.<br>
        RDP is waiting for the final HOPE callback.
        Admin Reset is available only from PUSHED.
    end note

    note right of MERGED
        Final merged status.<br>
        HOPE-side merge was confirmed.
        If a DE set exists, CW approves it during finalization.
    end note

    note right of REJECTED
        Final rejected status.<br>
        Can be set by DS reject, HOPE callback,
        clone replacement, or Admin Reset.
    end note
```

## Processing flow and policy rules

```mermaid
flowchart TB
    CREATE["Create RDP"] --> PENDING["PENDING<br>local processing"]

    PENDING --> DEDUP_CLAIM["Deduplicate action<br>claim RDP for dedup"]
    DEDUP_CLAIM --> DEDUP["Run DedupEngine flow<br>create/process existing set"]
    DEDUP -->|success or DE error| PENDING

    PENDING --> REJECT_DS["Reject Deduplication Set<br>DE REST API"]
    REJECT_DS -->|success| REJECTED["REJECTED<br>final rejected"]
    REJECT_DS -->|error| PENDING

    PENDING --> HOPE_PUSH["Push to HOPE Core<br>create RDI / push records / complete RDI"]
    HOPE_PUSH -->|failed| FAILURE["FAILURE<br>push failed"]
    HOPE_PUSH -->|succeeded| PUSHED["PUSHED<br>waiting for callback"]

    HOPE_CALLBACK["CW callback endpoint<br>POST /callbacks/hope/rdis/{hope_rdi_id}/"] --> CALLBACK["Apply final HOPE status"]
    PUSHED --> CALLBACK

    CALLBACK -->|MERGED| FINALIZE_MERGED["Approve DE set<br>if present"]
    FINALIZE_MERGED -->|ok| MERGED["MERGED<br>final merged"]
    FINALIZE_MERGED -->|DE error| PUSHED

    CALLBACK -->|REJECTED| FINALIZE_REJECTED["Reject DE set if present<br>restore beneficiaries"]
    FINALIZE_REJECTED -->|ok| REJECTED
    FINALIZE_REJECTED -->|DE error| PUSHED

    PUSHED --> RESET["Admin Reset<br>schedule AsyncJob"]
    RESET --> RESET_JOB["Reset job<br>reuse REJECTED finalization"]
    RESET_JOB --> FINALIZE_REJECTED

    CLONE["Clone RDP"] --> CLONE_CHECK{"Clone allowed?"}
    CLONE_CHECK -->|PENDING source| CLONE_PENDING["source REJECTED<br>child PENDING"]
    CLONE_CHECK -->|FAILURE / REJECTED source| CLONE_FINAL["source unchanged<br>child PENDING"]
    CLONE_CHECK -->|PUSHED / MERGED source| CLONE_BLOCKED["blocked"]
    CLONE_PENDING --> PENDING
    CLONE_FINAL --> PENDING

    subgraph STATUS_RULES["Status-based policy rules"]
        subgraph CREATE_RULES["Create / selection"]
            CR["BLOCK: empty or invalid selection, another PENDING RDP, or selected records already linked to PENDING/PUSHED/MERGED"]
            CB["BIOMETRIC: DE must allow creating a deduplication set before CW creates the RDP"]
        end

        subgraph DEDUP_RULES["Dedup / settings"]
            DR["DEDUP: PENDING + biometric only; create new DE set or process existing processable set"]
            DL["CLAIM: lock dedup settings; generate CW-owned deduplication_set_id when creating a new set"]
            RR["REJECT DS: PENDING + biometric + existing rejectable DE set"]
            SR["SETTINGS: blocked by PUSHED/MERGED or locked PENDING RDP"]
        end

        subgraph PUSH_RULES["Push"]
            PR["PUSH: PENDING only; non-biometric allowed, biometric requires pushable DE set"]
            PS["SUCCESS: send country_workspace_id when present, mark beneficiaries removed, set PUSHED"]
            PF["FAILURE: set FAILURE and keep the HOPE RDI id if one exists"]
        end

        subgraph CALLBACK_RULES["Callback / Reset"]
            CA["CALLBACK: authenticated by hope-api-auth grant; payload is MERGED or REJECTED; lookup by hope_rdi_id"]
            CF["FINALIZE: MERGED approves DE; REJECTED rejects DE and restores beneficiaries; DE error keeps PUSHED"]
            RA["RESET: PUSHED only; schedules AsyncJob; reuses REJECTED finalization"]
        end

        subgraph CLONE_RULES["Clone"]
            CL["CLONE: biometric only; block PUSHED/MERGED and any other pending RDP"]
            CD["REQUIRE: cloneable DE source; reuse deduplication_set_id only when source DE set is deduplicated"]
            CS["RESULT: PENDING source becomes REJECTED; FAILURE/REJECTED source stays unchanged; child is PENDING"]
        end
    end

    subgraph EXTERNAL["External service communication"]
        X1["DedupEngine REST API:<br>settings, create/process/reject DS, approve/reject DS, read status"]
        X2["HOPE Core outbound API:<br>sync reference data; create RDI; push people or individuals+households; complete RDI"]
        X3["CW inbound callback API:<br>authenticated final HOPE RDI outcome"]
    end

    classDef local fill:#E8F1FB,stroke:#4C78A8,stroke-width:1.5px,color:#1F2D3D;
    classDef external fill:#FDECC8,stroke:#D18F00,stroke-width:1.5px,color:#5C4400;
    classDef success fill:#E8F6EC,stroke:#2E8540,stroke-width:1.5px,color:#1F3D2A;
    classDef failed fill:#FBEAEA,stroke:#C43B3B,stroke-width:1.5px,color:#4A1F1F;
    classDef neutral fill:#F3F4F6,stroke:#6B7280,stroke-width:1.5px,color:#1F2937;
    classDef rejected fill:#F3E8FF,stroke:#7E22CE,stroke-width:1.5px,color:#3B0764;

    class PENDING,CREATE,DEDUP_CLAIM,CALLBACK,HOPE_CALLBACK,RESET,RESET_JOB,CLONE,CLONE_CHECK,CLONE_PENDING,CLONE_FINAL local;
    class DEDUP,REJECT_DS,HOPE_PUSH,FINALIZE_MERGED,FINALIZE_REJECTED,X1,X2,X3 external;
    class PUSHED,MERGED success;
    class FAILURE failed;
    class REJECTED rejected;
    class CLONE_BLOCKED,CR,CB,DR,DL,RR,SR,PR,PS,PF,CA,CF,RA,CL,CD,CS neutral;
```

## Key rules

* `PENDING` is local processing; `PUSHED` is a hand-off state waiting for the final HOPE callback; `FAILURE`, `REJECTED`, and `MERGED` are final statuses.
* CW handles Deduplication through DedupEngine, not HOPE Deduplication-flow endpoints.
* Dedup claim locks program dedup settings and may generate a CW-owned `deduplication_set_id`; settings stay blocked by locked `PENDING`, `PUSHED`, or `MERGED` RDPs.
* Successful HOPE push marks beneficiaries as removed, stores `hope_rdi_id`, and sets the RDP to `PUSHED`; failed push sets `FAILURE`.
* Final callback is authenticated by `hope-api-auth`, identifies the RDP by `hope_rdi_id`, and accepts only `MERGED` or `REJECTED`.
* Finalization syncs DE when needed: `MERGED` approves the set; `REJECTED` rejects the set and restores removed beneficiaries. DE sync failure leaves the RDP `PUSHED`.
* Admin Reset is only for `PUSHED` RDPs and reuses the same `REJECTED` finalization path.
* Clone requires a biometric program and a cloneable DE source; `PENDING` source becomes `REJECTED`, `FAILURE/REJECTED` source stays unchanged, and the child starts as `PENDING`.
