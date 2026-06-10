## RDP state flow

```mermaid
stateDiagram-v2
    [*] --> PENDING: Create RDP or Clone child

    PENDING --> PENDING: Dedup via DE REST
    PENDING --> FAILURE: Push failed
    PENDING --> PUSHED: Push succeeded
    PENDING --> REJECTED: Reject DS
    PENDING --> REJECTED: Clone replaces source

    PUSHED --> MERGED: HOPE callback MERGED
    PUSHED --> REJECTED: HOPE callback REJECTED
    PUSHED --> REJECTED: Admin Reset job applies HOPE REJECTED flow
    PUSHED --> PUSHED: Admin Reset job failed

    FAILURE --> [*]: Final failed
    REJECTED --> [*]: Final rejected
    MERGED --> [*]: Final merged

    note right of PENDING
        Local active RDP status.<br>
        For a new DE set, CW ensures deduplication_set_id before creation.
        deduplication_set_id belongs to selection owner / dedup source.
        RDP remains PENDING after dedup success or DE error.
    end note

    note right of FAILURE
        Push workflow failed.<br>
        RDP was not successfully handed off to HOPE Core.
    end note

    note right of PUSHED
        CW pushed data to HOPE Core successfully.<br>
        RDP is waiting for the final HOPE callback.
        Admin Reset is available only from PUSHED and schedules an async job.
    end note

    note right of MERGED
        Final merged RDP status.<br>
        HOPE-side merge was confirmed.
        If a DE set exists, CW approves it during callback processing.
    end note

    note right of REJECTED
        Final rejected RDP status.<br>
        Can be set by DE set reject,
        HOPE callback REJECTED,
        Clone replacing PENDING source,
        or Admin Reset job using the HOPE REJECTED flow.
    end note
```

## Processing flow and policy rules

```mermaid
flowchart TB
    CREATE["Create RDP"] --> PENDING["PENDING<br>local active"]

    PENDING --> DEDUP_CLAIM["Deduplicate action<br>CW ensures deduplication_set_id"]
    DEDUP_CLAIM --> DEDUP["Run DE deduplication<br>create/upload/process or process existing"]
    DEDUP --> D1{"DE result"}
    D1 -- "new set" --> PENDING
    D1 -- "existing set" --> PENDING
    D1 -- "error" --> PENDING

    PENDING --> RDS["Reject Deduplication Set<br>DE REST API"]
    RDS -->|rejected| REJECTED["REJECTED<br>final rejected state"]
    RDS -->|error| PENDING

    PENDING --> HOPE_PUSH["Push to HOPE<br>create RDI / push / complete"]
    HOPE_PUSH -->|failed| FAILURE["FAILURE<br>push workflow failed"]
    HOPE_PUSH -->|succeeded| PUSHED["PUSHED<br>waiting for HOPE final callback"]

    PUSHED --> CALLBACK["HOPE final callback"]

    CALLBACK -->|MERGED| FINALIZE_MERGED["Approve Deduplication Set<br>if present"]
    FINALIZE_MERGED -->|ok| MERGED["MERGED<br>merged in HOPE Core"]
    FINALIZE_MERGED -->|DE error| PUSHED

    CALLBACK -->|REJECTED| FINALIZE_REJECTED["Reject Deduplication Set if present<br>restore removed beneficiaries"]
    FINALIZE_REJECTED -->|ok| REJECTED["REJECTED<br>final rejected state"]
    FINALIZE_REJECTED -->|DE error| PUSHED

    PUSHED --> RESET["Staff admin Reset<br>schedule AsyncJob"]
    RESET --> RESET_JOB["Reset RDP job<br>reuse HOPE REJECTED callback flow"]
    RESET_JOB --> FINALIZE_REJECTED

    CLONE["Clone RDP"] --> CL1{"source status"}
    CL1 -- "PENDING" --> CL2["source becomes REJECTED<br>child becomes PENDING"]
    CL1 -- "FAILURE / REJECTED" --> CL3["source unchanged<br>child becomes PENDING"]
    CL1 -- "PUSHED / MERGED" --> CL4["clone blocked"]

    CL2 --> PENDING
    CL3 --> PENDING

    subgraph STATUS_RULES["Status-based policy rules"]
        subgraph CREATE_RULES["Regular Create RDP"]
            A["BLOCK: Program has PENDING RDP"]
            B["BLOCK: selected records are already linked to PENDING/PUSHED/MERGED RDP"]
        end

        subgraph DEDUP_RULES["Run Deduplication"]
            H["ENSURE: CW-owned deduplication_set_id before new DE set creation"]
            J["LOCK: Program dedup settings after deduplication is requested"]
        end

        subgraph CLONE_RULES["Clone RDP"]
            C["ALLOW: clone PENDING; source becomes REJECTED, child becomes PENDING"]
            D["ALLOW: clone FAILURE/REJECTED; source unchanged, child becomes PENDING"]
            E["BLOCK: clone PUSHED/MERGED"]
            F["REQUIRE: DE state allows clone: failed encoding, failed dedup, deduplicated, or rejected"]
            K["REUSE: child may keep source deduplication_set_id when source DE set is deduplicated"]
        end

        subgraph SETTINGS_RULES["Update Dedup Settings"]
            G["BLOCK: PENDING locked by dedup request, PUSHED, or MERGED RDP"]
        end

        subgraph PUSH_RULES["Push to HOPE"]
            L["SEND: RDI country_workspace_id = deduplication_set_id when present"]
            M["SEND: beneficiary identifiers as required by HOPE Core"]
            N["MARK: pushed beneficiaries as removed"]
            O["SET: RDP status to PUSHED after successful HOPE push"]
        end

        subgraph CALLBACK_RULES["HOPE final callback"]
            P["MERGED: approve DE set if present"]
            Q["REJECTED: reject DE set if present"]
            R["REJECTED: restore removed beneficiaries"]
            S["KEEP PUSHED: DE callback sync error does not finalize RDP"]
        end

        subgraph RESET_RULES["Admin Reset"]
            T["ALLOW: only PUSHED RDP"]
            U["SCHEDULE: AsyncJob from admin button"]
            V["REUSE: HOPE REJECTED callback finalization flow"]
            W["KEEP PUSHED: reset job error does not finalize RDP"]
        end
    end

    subgraph EXTERNAL["External service communication"]
        X1["DE REST API:<br>settings, create/process/reject DS, approve/reject DS, read status"]
        X2["HOPE Core API:<br>create RDI, push people or individuals+households, complete RDI, final callback"]
    end

    classDef local fill:#E8F1FB,stroke:#4C78A8,stroke-width:1.5px,color:#1F2D3D;
    classDef external fill:#FDECC8,stroke:#D18F00,stroke-width:1.5px,color:#5C4400;
    classDef success fill:#E8F6EC,stroke:#2E8540,stroke-width:1.5px,color:#1F3D2A;
    classDef failed fill:#FBEAEA,stroke:#C43B3B,stroke-width:1.5px,color:#4A1F1F;
    classDef neutral fill:#F3F4F6,stroke:#6B7280,stroke-width:1.5px,color:#1F2937;
    classDef rejected fill:#F3E8FF,stroke:#7E22CE,stroke-width:1.5px,color:#3B0764;

    class PENDING,CREATE,CLONE,CL1,CL2,CL3,RESET,RESET_JOB,DEDUP_CLAIM,CALLBACK local;
    class DEDUP,D1,RDS,HOPE_PUSH,FINALIZE_MERGED,FINALIZE_REJECTED,X1,X2 external;
    class PUSHED,MERGED success;
    class FAILURE failed;
    class REJECTED rejected;
    class CL4,A,B,C,D,E,F,G,H,J,K,L,M,N,O,P,Q,R,S,T,U,V,W neutral;
```

## Key rules

* `PENDING` is the only local active RDP status.
* For a new DedupEngine set, `deduplication_set_id` is generated by CW before the create call.
* RDI `country_workspace_id` is sent only when the RDP has `deduplication_set_id`; its value is `str(deduplication_set_id)`.
* `deduplication_set_id` belongs to the selection owner / deduplication source, so clones may reuse it.
* `PUSHED` means CW successfully completed the HOPE push and is waiting for the final HOPE callback.
* `MERGED` means HOPE-side merge was confirmed.
* `REJECTED` means the RDP was rejected locally, by HOPE callback, by clone replacement, or by Admin Reset.
* If a DedupEngine set exists, final DE sync is performed during finalization: `MERGED` approves the set, `REJECTED` rejects it.
* If DE final sync fails during callback processing, the callback fails and RDP remains `PUSHED`.
* Admin Reset is available only for `PUSHED` RDPs and schedules an async job.
* Admin Reset reuses the same finalization path as a HOPE `REJECTED` callback: reject DE set if present, restore removed beneficiaries, and mark RDP as `REJECTED`.
* If Admin Reset finalization fails, the job fails and RDP remains `PUSHED`.
