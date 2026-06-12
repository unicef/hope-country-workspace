## RDP state flow

```mermaid
stateDiagram-v2
    [*] --> PENDING: Create RDP / Clone child

    PENDING --> PENDING: Dedup attempt
    PENDING --> FAILURE: Push failed before hand-off
    PENDING --> PUSHED: HOPE hand-off completed
    PENDING --> REJECTED: DedupEngine set rejected
    PENDING --> REJECTED: Replaced by clone

    PUSHED --> MERGED: HOPE callback MERGED
    PUSHED --> REJECTED: HOPE callback REJECTED
    PUSHED --> REJECTED: Admin Reset: manual REJECTED
    PUSHED --> PUSHED: DE sync failed

    FAILURE --> [*]
    REJECTED --> [*]
    MERGED --> [*]

    note right of PENDING
        Open CW state.<br>
        RDP can still be deduplicated, rejected, cloned, or pushed.
    end note

    note right of PUSHED
        HOPE hand-off is complete.<br>
        CW waits for the final HOPE outcome.
        If final DE sync fails, the RDP stays PUSHED.
    end note

    note right of MERGED
        Final accepted outcome.<br>
        HOPE confirmed the RDI merge.
    end note

    note right of REJECTED
        Final rejected outcome.<br>
        The RDP is closed without a successful merge.
    end note

    note right of FAILURE
        Final push failure.<br>
        CW did not complete the HOPE hand-off.
    end note
```

## Processing flow

```mermaid
flowchart TB

    CREATE["Create RDP"] --> PENDING["PENDING<br/>CW open state"]

    PENDING --> DEDUP["Run deduplication<br/>DE create/process"]
    DEDUP -->|done / error| PENDING

    PENDING --> REJECT_SET["Reject DE set"]
    REJECT_SET -->|ok| REJECTED["REJECTED<br/>closed"]
    REJECT_SET -->|DE error| PENDING

    PENDING --> PUSH["Push to HOPE"]
    PUSH -->|hand-off failed| FAILURE["FAILURE<br/>closed"]
    PUSH -->|hand-off ok| PUSHED["PUSHED<br/>waiting for HOPE"]

    PUSHED --> OUTCOME{"HOPE outcome"}

    OUTCOME -->|MERGED| APPROVE_DE["Approve DE set"]
    APPROVE_DE -->|ok| MERGED["MERGED<br/>closed"]
    APPROVE_DE -->|DE error| PUSHED

    OUTCOME -->|REJECTED| REJECT_DE["Reject DE set"]
    REJECT_DE -->|ok| RESTORE["Restore records"]
    REJECT_DE -->|DE error| PUSHED
    RESTORE --> REJECTED

    PUSHED --> RESET["Admin Reset"]
    RESET --> RESET_JOB["Schedule reset job"]
    RESET_JOB --> REJECT_DE

    CLONE["Clone RDP"] --> CLONE_SOURCE{"Source status"}
    CLONE_SOURCE -->|PENDING| CLONE_PENDING["source → REJECTED<br/>child → PENDING"]
    CLONE_SOURCE -->|FAILURE / REJECTED| CLONE_FINAL["source unchanged<br/>child → PENDING"]
    CLONE_SOURCE -->|PUSHED / MERGED| CLONE_BLOCKED["blocked"]

    CLONE_PENDING --> PENDING
    CLONE_FINAL --> PENDING

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

    class CREATE,PENDING,OUTCOME,RESET,RESET_JOB,RESTORE,CLONE,CLONE_SOURCE,CLONE_PENDING,CLONE_FINAL,CW_CB local;
    class DEDUP,REJECT_SET,APPROVE_DE,REJECT_DE,DE_API de;
    class PUSH,HOPE_API hope;
    class PUSHED,MERGED success;
    class FAILURE failed;
    class REJECTED rejected;
    class CLONE_BLOCKED rule;
```

## Policy rules

```mermaid
flowchart TB

    subgraph RULES["Status-based policy rules"]
        direction LR

        subgraph PRE_PUSH_RULES["Before push"]
            direction LR

            subgraph CREATE_RULES["Create RDP"]
                direction TB

                C1["ALLOW: valid non-empty selection"]
                C2["BLOCK: program has PENDING RDP"]
                C3["BLOCK: selected records are in PENDING / PUSHED / MERGED RDP"]
            end

            subgraph DEDUP_RULES["Run Deduplication"]
                direction TB

                D1["ALLOW: biometric PENDING RDP"]
                D2["ENSURE: CW-owned deduplication_set_id"]
                D3["LOCK: dedup settings after request"]
                D4["KEEP: status remains PENDING"]
            end

            subgraph REJECT_SET_RULES["Reject DE Set"]
                direction TB

                RS1["ALLOW: PENDING RDP with active DE set"]
                RS2["SUCCESS: set REJECTED"]
                RS3["FAILURE: keep PENDING"]
            end

            subgraph SETTINGS_RULES["Update Dedup Settings"]
                direction TB

                S1["ALLOW: no locked PENDING and no PUSHED / MERGED RDP"]
                S2["BLOCK: dedup already requested"]
                S3["BLOCK: PUSHED / MERGED RDP exists"]
            end
        end

        subgraph PUSH_FINAL_RULES["Push and finalization"]
            direction LR

            subgraph PUSH_RULES["Push to HOPE"]
                direction TB

                P1["ALLOW: PENDING RDP"]
                P2["REQUIRE: biometric needs pushable DE state"]
                P3["SUCCESS: store hope_rdi_id, remove records, set PUSHED"]
                P4["FAILURE: set FAILURE if hand-off did not complete"]
            end

            subgraph FINALIZE_RULES["Finalize HOPE Outcome"]
                direction TB

                F1["ALLOW: PUSHED RDP"]
                F2["MERGED: approve DE set, then set MERGED"]
                F3["REJECTED: reject DE set, restore records, then set REJECTED"]
                F4["FAILURE: keep PUSHED if DE sync fails"]
            end

            subgraph RESET_RULES["Admin Reset"]
                direction TB

                R1["ALLOW: PUSHED RDP"]
                R2["SCHEDULE: reset job"]
                R3["REUSE: REJECTED finalization path"]
                R4["FAILURE: keep PUSHED if finalization fails"]
            end
        end

        subgraph CLONE_POLICY_RULES["Clone RDP"]
            direction TB

            CL1["ALLOW: source PENDING → source REJECTED, child PENDING"]
            CL2["ALLOW: source FAILURE / REJECTED → source unchanged, child PENDING"]
            CL3["BLOCK: source PUSHED / MERGED"]
            CL4["REQUIRE: biometric source must be cloneable"]
        end
    end

    classDef allow fill:#E8F6EC,stroke:#2E8540,stroke-width:1.5px,color:#1F3D2A;
    classDef block fill:#FBEAEA,stroke:#C43B3B,stroke-width:1.5px,color:#4A1F1F;
    classDef require fill:#FFF3CD,stroke:#B7791F,stroke-width:1.5px,color:#5C4400;
    classDef success fill:#E6FFFA,stroke:#319795,stroke-width:1.5px,color:#1D4044;
    classDef failed fill:#FBEAEA,stroke:#C43B3B,stroke-width:1.5px,color:#4A1F1F;
    classDef keep fill:#F3F4F6,stroke:#6B7280,stroke-width:1.5px,color:#1F2937;
    classDef action fill:#E8F1FB,stroke:#4C78A8,stroke-width:1.5px,color:#1F2D3D;

    class C1,D1,RS1,S1,P1,F1,R1,CL1,CL2 allow;
    class C2,C3,S2,S3,CL3 block;
    class D2,P2,CL4 require;
    class RS2,P3,F2,F3 success;
    class P4 failed;
    class D3,R2,R3 action;
    class D4,RS3,F4,R4 keep;
```


## Integration boundaries

* CW owns the RDP lifecycle and applies business rules for create, dedup, push, reset, clone, and finalization.
* DedupEngine owns deduplication set state and decisions.
* HOPE Core owns RDI processing and the final merge/rejection outcome.
* CW receives the authenticated HOPE callback and applies that outcome to the RDP.
