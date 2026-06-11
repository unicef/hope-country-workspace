## RDP state flow

```mermaid
stateDiagram-v2
    [*] --> PENDING: Create RDP / Clone child

    PENDING --> PENDING: Dedup attempt
    PENDING --> FAILURE: HOPE push failed
    PENDING --> PUSHED: HOPE push completed
    PENDING --> REJECTED: DedupEngine set rejected
    PENDING --> REJECTED: Replaced by clone

    PUSHED --> MERGED: HOPE callback MERGED
    PUSHED --> REJECTED: HOPE callback REJECTED
    PUSHED --> REJECTED: Admin Reset: manual REJECTED
    PUSHED --> PUSHED: Finalization failed

    FAILURE --> [*]
    REJECTED --> [*]
    MERGED --> [*]

    note right of PENDING
        CW is preparing the RDP.
        Deduplication and push decisions are still local.
    end note

    note right of PUSHED
        CW handed the RDI to HOPE Core.
        The RDP waits for the final HOPE outcome.
    end note

    note right of MERGED
        Final successful outcome.
        HOPE confirmed merge.
    end note

    note right of REJECTED
        Final rejected outcome.
        Selection may be released/restored depending on the path.
    end note

    note right of FAILURE
        CW push failed before a successful HOPE hand-off.
    end note
```


## Processing flow and policy rules

```mermaid
flowchart TB
    CREATE["Create RDP"] --> PENDING["PENDING<br>CW preparation"]

    PENDING --> DEDUP_CLAIM["Claim deduplication"]
    DEDUP_CLAIM --> DEDUP["Create or process<br>DedupEngine set"]
    DEDUP -->|done / error| PENDING

    PENDING --> REJECT_DS["Reject active<br>DedupEngine set"]
    REJECT_DS -->|ok| REJECTED["REJECTED<br>final rejected"]
    REJECT_DS -->|error| PENDING

    PENDING --> HOPE_PUSH["Push RDI to HOPE Core"]
    HOPE_PUSH -->|failed| FAILURE["FAILURE<br>push failed"]
    HOPE_PUSH -->|completed| PUSHED["PUSHED<br>waiting for final outcome"]

    PUSHED --> OUTCOME{"Final outcome"}

    OUTCOME -->|HOPE callback: MERGED| APPROVE_DE["Approve DedupEngine set<br>if present"]
    APPROVE_DE -->|ok| MERGED["MERGED<br>final merged"]
    APPROVE_DE -->|DE error| PUSHED

    OUTCOME -->|HOPE callback: REJECTED| REJECT_DE["Reject DedupEngine set<br>if present"]
    PUSHED --> RESET["Admin Reset<br>manual REJECTED path"]
    RESET --> RESET_JOB["Schedule reset job"]
    RESET_JOB --> REJECT_DE

    REJECT_DE -->|ok| RESTORE["Restore removed beneficiaries"]
    REJECT_DE -->|DE error| PUSHED
    RESTORE --> REJECTED

    CLONE["Clone RDP"] --> CLONE_RULES{"Cloneable source?"}
    CLONE_RULES -->|PENDING| CLONE_PENDING["source REJECTED<br>child PENDING"]
    CLONE_RULES -->|FAILURE / REJECTED| CLONE_FINAL["source unchanged<br>child PENDING"]
    CLONE_RULES -->|PUSHED / MERGED| CLONE_BLOCKED["blocked"]
    CLONE_PENDING --> PENDING
    CLONE_FINAL --> PENDING

    subgraph RULES["Business rules"]
        direction LR

        R1["Create: valid, non-empty selection"] ~~~
        R2["Create guard: only one PENDING RDP per program"] ~~~
        R3["Dedup: biometric, PENDING RDP only"] ~~~
        R4["Dedup result: RDP stays PENDING"]

        R5["Push: PENDING only, biometric, requires pushable DE state"] ~~~
        R6["Push result: success sets PUSHED, failure sets FAILURE"] ~~~
        R7["Finalize: PUSHED only, DE error keeps PUSHED"] ~~~
        R8["Reset / Clone: reset rejects, clone creates PENDING child"]
    end

    subgraph SERVICES["External integrations"]
        DE_API["DedupEngine<br>deduplication settings, set status, create/process, approve/reject"]
        HOPE_API["HOPE Core<br>RDI creation, record push, completion, final outcome"]
        CW_CB["CW callback endpoint<br>authenticated receiver for HOPE final outcome"]
    end

    classDef local fill:#E8F1FB,stroke:#4C78A8,stroke-width:1.5px,color:#1F2D3D;
    classDef de fill:#E8F6EC,stroke:#2E8540,stroke-width:1.5px,color:#1F3D2A;
    classDef hope fill:#FFF3CD,stroke:#B7791F,stroke-width:1.5px,color:#5C4400;
    classDef success fill:#E6FFFA,stroke:#319795,stroke-width:1.5px,color:#1D4044;
    classDef failed fill:#FBEAEA,stroke:#C43B3B,stroke-width:1.5px,color:#4A1F1F;
    classDef rejected fill:#F3E8FF,stroke:#7E22CE,stroke-width:1.5px,color:#3B0764;
    classDef rule fill:#F3F4F6,stroke:#6B7280,stroke-width:1.5px,color:#1F2937;

    class CREATE,PENDING,DEDUP_CLAIM,OUTCOME,RESET,RESET_JOB,RESTORE,CLONE,CLONE_RULES,CLONE_PENDING,CLONE_FINAL local;
    class DEDUP,REJECT_DS,APPROVE_DE,REJECT_DE,DE_API de;
    class HOPE_PUSH,HOPE_API hope;
    class CW_CB local;
    class PUSHED,MERGED success;
    class FAILURE failed;
    class REJECTED rejected;
    class CLONE_BLOCKED,R1,R2,R3,R4,R5,R6,R7,R8 rule;
```


## Integration boundaries

* CW owns the RDP lifecycle and applies business rules for create, dedup, push, reset, clone, and finalization.
* DedupEngine owns deduplication set state and decisions.
* HOPE Core owns RDI processing and the final merge/rejection outcome.
* CW receives the authenticated HOPE callback and applies that outcome to the RDP.
