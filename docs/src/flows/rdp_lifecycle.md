This page describes the current RDP lifecycle and the main processing rules for DedupEngine and HOPE Core integration.

## RDP state flow

```mermaid
stateDiagram-v2
    [*] --> PENDING: Create RDP or Clone child

    PENDING --> PENDING: Dedup via DE REST
    PENDING --> FAILURE: Push failed
    PENDING --> SUCCESS: Push succeeded
    PENDING --> CANCELLED: Admin cancel
    PENDING --> CANCELLED: Reject DS
    PENDING --> CANCELLED: Clone replaces source

    SUCCESS --> CANCELLED: Staff Reset after HOPE rejection

    FAILURE --> [*]: Final failed
    CANCELLED --> [*]: Final cancelled
    SUCCESS --> [*]: Final successful

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

    note right of SUCCESS
        Final successful RDP status.<br>
        CW pushed data to HOPE Core successfully.
        HOPE Core automerge is assumed.
        If a DE set exists, CW calls DE approve after successful push.
        DE approve failure is recorded but does not change RDP status.
    end note

    note right of CANCELLED
        Final cancelled RDP status.<br>
        Can be set by admin cancel, DE set reject,
        Clone replacing PENDING source, or Staff Reset.
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
    RDS -->|rejected| CANCELLED["CANCELLED<br>final cancelled state"]
    RDS -->|error| PENDING

    PENDING --> HOPE_PUSH["Push to HOPE<br>create RDI / push / complete"]
    HOPE_PUSH -->|failed| FAILURE["FAILURE<br>push workflow failed"]
    HOPE_PUSH -->|succeeded| SUCCESS["SUCCESS<br>pushed to HOPE Core<br>automerge assumed"]

    SUCCESS -. "post-push" .-> DE_APPROVE["Approve Deduplication Set<br>DE REST API"]
    DE_APPROVE -. "status unchanged" .-> SUCCESS

    SUCCESS --> RESET["Staff admin Reset"]
    RESET -->|HOPE rejection confirmed| CANCELLED

    PENDING -->|admin cancels RDP| CANCELLED

    CLONE["Clone RDP"] --> CL1{"source status"}
    CL1 -- "PENDING" --> CL2["source becomes CANCELLED<br>child becomes PENDING"]
    CL1 -- "FAILURE / CANCELLED" --> CL3["source unchanged<br>child becomes PENDING"]
    CL1 -- "SUCCESS" --> CL4["clone blocked"]

    CL2 --> PENDING
    CL3 --> PENDING

    subgraph STATUS_RULES["Status-based policy rules"]
        subgraph CREATE_RULES["Regular Create RDP"]
            A["BLOCK: Program has PENDING RDP"]
            B["BLOCK: selected records are already linked to PENDING/SUCCESS RDP"]
        end

        subgraph DEDUP_RULES["Run Deduplication"]
            H["ENSURE: CW-owned deduplication_set_id before new DE set creation"]
            J["BLOCK: Deduplicate cannot be started twice for the same RDP"]
        end

        subgraph CLONE_RULES["Clone RDP"]
            C["ALLOW: clone PENDING; source becomes CANCELLED, child becomes PENDING"]
            D["ALLOW: clone FAILURE/CANCELLED; source unchanged, child becomes PENDING"]
            E["BLOCK: clone SUCCESS"]
            F["REQUIRE: DE state allows clone: failed encoding, failed dedup, deduplicated, or rejected"]
            K["REUSE: child may keep source deduplication_set_id when source DE set is deduplicated"]
        end

        subgraph SETTINGS_RULES["Update Dedup Settings"]
            G["BLOCK: PENDING RDP after deduplication was requested, or SUCCESS RDP"]
        end

        subgraph PUSH_RULES["Push to HOPE"]
            L["SEND: RDI country_workspace_id = deduplication_set_id when present"]
            M["SEND: beneficiary country_workspace_id as required by HOPE Core"]
            N["APPROVE: DE set after successful HOPE push, if present"]
            O["KEEP SUCCESS: DE approve error is recorded only"]
        end
    end

    subgraph EXTERNAL["External service communication"]
        X1["DE REST API:<br>settings, create/process/reject/approve DS, read status"]
        X2["HOPE Core API:<br>create RDI, push people or individuals+households, complete RDI"]
    end

    classDef local fill:#E8F1FB,stroke:#4C78A8,stroke-width:1.5px,color:#1F2D3D;
    classDef external fill:#FDECC8,stroke:#D18F00,stroke-width:1.5px,color:#5C4400;
    classDef success fill:#E8F6EC,stroke:#2E8540,stroke-width:1.5px,color:#1F3D2A;
    classDef failed fill:#FBEAEA,stroke:#C43B3B,stroke-width:1.5px,color:#4A1F1F;
    classDef neutral fill:#F3F4F6,stroke:#6B7280,stroke-width:1.5px,color:#1F2937;
    classDef cancelled fill:#F3E8FF,stroke:#7E22CE,stroke-width:1.5px,color:#3B0764;

    class PENDING,CREATE,CLONE,CL1,CL2,CL3,RESET,DEDUP_CLAIM local;
    class DEDUP,D1,RDS,HOPE_PUSH,DE_APPROVE,X1,X2 external;
    class SUCCESS success;
    class FAILURE failed;
    class CANCELLED cancelled;
    class CL4,A,B,C,D,E,F,G,H,I,J,K,L,M,N,O neutral;
```

## Key rules

- `PENDING` is the only local active RDP status.
- For a new DedupEngine set, `deduplication_set_id` is generated by CW before the create call.
- RDI `country_workspace_id` is sent only when the RDP has `deduplication_set_id`; its value is `str(deduplication_set_id)`.
- `deduplication_set_id` belongs to the selection owner / deduplication source, so clones may reuse it.
- `SUCCESS` means CW successfully completed the HOPE push; HOPE Core automerge is assumed.
- If a DedupEngine set exists, approve is called after successful HOPE push. Approval errors are recorded, but RDP status stays `SUCCESS`.
- Staff Reset can move `SUCCESS` to `CANCELLED` when HOPE-side rejection is confirmed manually.
