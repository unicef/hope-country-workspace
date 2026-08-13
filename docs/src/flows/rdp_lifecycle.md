This page describes the current RDP lifecycle and the main processing rules for DedupEngine and HOPE Core integration.

## RDP state flow

```mermaid
stateDiagram-v2
    [*] --> PENDING: Create RDP

    PENDING --> PENDING: Manual deduplication (status unchanged)
    FAILURE --> FAILURE: Manual deduplication (status unchanged)

    PENDING --> PUSH_PENDING: Start push
    FAILURE --> PUSH_PENDING: Retry push

    PUSH_PENDING --> FAILURE: Preparation or data push failed
    PUSH_PENDING --> FAILURE: Fail stuck push
    PUSH_PENDING --> SUCCESS: Push succeeded

    PENDING --> CANCELLED: Cancel RDP
    FAILURE --> CANCELLED: Cancel RDP

    SUCCESS --> CANCELLED: Staff Reset latest successful RDP

    PENDING --> DEDUP_PENDING: Automatic create+push flow
    DEDUP_PENDING --> PUSH_PENDING: Dedup callback allows push
    DEDUP_PENDING --> FAILURE: Dedup failed or threshold exceeded

    note right of PENDING
        Open local RDP status.<br>
        New RDPs are created as PENDING.<br>
        Manual deduplication does not change this status.
    end note

    note right of DEDUP_PENDING
        Waiting for a DedupEngine callback.<br>
        Used by the automatic create+push flow,<br>
        which is disabled by default behind the feature flag.
    end note

    note right of PUSH_PENDING
        Active HOPE push attempt.<br>
        Includes RDI reset preparation,<br>
        callback waiting, and data push.
    end note

    note right of FAILURE
        Open retry status.<br>
        Dedup or HOPE push workflow failed.<br>
        Push can be retried.
    end note

    note right of SUCCESS
        CW successfully completed the HOPE push.<br>
        Related beneficiaries were marked as removed.
    end note

    note right of CANCELLED
        Cancelled RDP status.<br>
        No further RDP workflow actions are expected.
    end note
```

## Processing sequence

Most RDP actions are performed from the analyst workspace. Staff Reset and stuck-push recovery are shown from the standard Django admin.

```mermaid
sequenceDiagram
    participant Staff as Staff Admin
    participant Analyst as Analyst Admin
    participant App as CW App
    participant DB as CW Database
    participant DE as DedupEngine
    participant HOPE as HOPE Core

    opt Optional: update dedup settings before RDP processing starts
        Analyst->>App: Update dedup settings
        App->>DB: Check program can update DE settings
        Note over App,DB: Blocked after SUCCESS or while dedup/push is queued or running

        alt Update blocked
            App-->>Analyst: Show settings error
        else Update allowed
            App->>DE: Read current dedup settings
            Analyst->>App: Submit updated settings
            App->>DB: Recheck update is allowed
            App->>DE: Save updated dedup settings
        end
    end

    Analyst->>App: Create RDP
    App->>DB: Run RDP preflight checks

    alt Create blocked
        App-->>Analyst: Show create error
    else Create allowed
        App->>DB: Save RDP as PENDING
    end

    opt Optional: run manual deduplication for biometric RDP
        Analyst->>App: Run deduplication
        App->>DB: Check dedup can start
        App->>DE: Create or process DS
        App->>DB: Append dedup operation log
        Note over DB: RDP stays PENDING or FAILURE
    end

    Analyst->>App: Push or retry push
    App->>DB: Claim push and set PUSH_PENDING
    App->>DB: Queue preparation AsyncJob

    alt No previous HOPE RDI
        App->>DB: Queue data-push AsyncJob
    else Previous HOPE RDI exists
        App->>HOPE: Request RDI reset with callback URL

        alt Reset accepted
            Note over App,DB: Keep PUSH_PENDING
            HOPE-->>App: Push-ready callback
            App->>DB: Queue data-push AsyncJob
        else Previous RDI not found
            App->>DB: Queue data-push AsyncJob
        else RDI merge in progress
            App->>DB: Set FAILURE
        else Previous RDI already merged
            App->>DB: Mark records removed and set SUCCESS
            App->>DE: Try approve DS if present
        end
    end

    opt Data-push AsyncJob queued
        App->>HOPE: Create new RDI
        App->>HOPE: Push beneficiaries
        App->>HOPE: Complete RDI

        alt Push failed
            App->>DB: Set FAILURE
        else Push succeeded
            App->>DB: Mark records removed and set SUCCESS
            App->>DE: Try approve DS if present
            Note over DB,DE: DE approval does not change local SUCCESS
        end
    end

    opt Temporary recovery for stuck PUSH_PENDING
        Staff->>App: Fail stuck push
        App->>DB: Verify active attempt and no data-push job
        App->>DB: Set FAILURE
    end

    opt Optional: cancel open RDP
        Analyst->>App: Cancel RDP
        App->>DB: Check cancel can start

        alt Cancel blocked
            App-->>Analyst: Show cancel error
        else Cancel allowed
            App->>DE: Reject DS if Deduplicated
            App->>DB: Set CANCELLED
        end
    end

    opt Optional: staff recovery after SUCCESS
        Staff->>App: Reset latest successful RDP
        App->>DB: Set related beneficiaries removed=False and set CANCELLED
    end
```

## Policy gates and side effects

```mermaid
flowchart TB
    subgraph SETTINGS["Update dedup settings"]
        S1["ALLOW: biometric program"]
        S2["BLOCK: SUCCESS RDP exists"]
        S3["BLOCK: dedup or push is queued/running"]
        S4["SAVE: program-level DE settings"]
    end

    subgraph CREATE["Create RDP"]
        C1["ALLOW: selection passes RDP preflight"]
        C2["BLOCK: empty selection or invalid records"]
        C3["BLOCK: records already linked to unfinished or SUCCESS RDP"]
        C4["BLOCK: biometric program cannot create a new DS"]
    end

    subgraph DEDUP["Manual Deduplicate"]
        D1["ALLOW: biometric RDP is PENDING or FAILURE"]
        D2["BLOCK: dedup already queued/running"]
        D3["RUN: create new DS or process existing READY DS"]
        D4["KEEP STATUS: PENDING or FAILURE"]
    end

    subgraph PUSH["Push to HOPE"]
        P1["ALLOW: RDP is PENDING or FAILURE"]
        P2["SET: PUSH_PENDING for the active attempt"]
        P3["REQUIRE: Deduplicated DS for biometric push"]
        P4["RESET: existing HOPE RDI; already merged means SUCCESS"]
        P5["QUEUE: separate data-push AsyncJob"]
        P6["SET: SUCCESS or FAILURE"]
    end

    subgraph CANCEL["Cancel RDP"]
        X1["ALLOW: RDP is PENDING or FAILURE"]
        X2["BLOCK: dedup is queued/running"]
        X3["BLOCK: DE set is running"]
        X4["REJECT: DS only when Deduplicated"]
        X5["SET: CANCELLED"]
    end

    subgraph RESET["Staff Reset"]
        R1["ALLOW: latest successful RDP only"]
        R2["RESTORE: related beneficiaries removed=False"]
        R3["SET: CANCELLED"]
    end

    subgraph CLEANUP["Batch cleanup"]
        B1["BLOCK: batch is referenced by an unfinished RDP"]
    end

    subgraph SERVICES["External services"]
        DE_API["DedupEngine<br>settings, status, processing, approve/reject"]
        HOPE_API["HOPE Core<br>reset/create RDI, beneficiary push, callbacks"]
    end

    classDef rule fill:#F3F4F6,stroke:#6B7280,stroke-width:1.5px,color:#1F2937;
    classDef external fill:#FDECC8,stroke:#D18F00,stroke-width:1.5px,color:#5C4400;

    class S1,S2,S3,S4,C1,C2,C3,C4,D1,D2,D3,D4,P1,P2,P3,P4,P5,P6,X1,X2,X3,X4,X5,R1,R2,R3,B1 rule;
    class DE_API,HOPE_API external;
```

## Key rules

* `PENDING` and `FAILURE` are the manual working statuses.
* Manual deduplication does not change the RDP status.
* Push sets `PUSH_PENDING`; only the active push attempt can continue.
* Existing HOPE RDI reset may wait for a callback, fail on merge in progress, or finish as `SUCCESS` if already merged.
* HOPE readiness callback queues a separate data-push AsyncJob.
* Successful push sets `SUCCESS`; failures set `FAILURE`.
* DedupEngine approve runs after successful push and does not change `SUCCESS`.
* Cancel is allowed only from `PENDING` or `FAILURE`.
* Staff Reset changes the latest `SUCCESS` RDP to `CANCELLED`.
* Batch cleanup is blocked for batches referenced by unfinished RDPs.
* Automatic create+push is disabled by default behind the `AUTOMATIC_RDP_PUSH` feature flag.
