This page describes the current RDP lifecycle and the main processing rules for DedupEngine and HOPE Core integration.

## RDP state flow

```mermaid
stateDiagram-v2
    [*] --> PENDING: Create RDP

    PENDING --> PENDING: Dedup completed or failed
    FAILURE --> FAILURE: Dedup completed or failed

    PENDING --> FAILURE: Push failed
    FAILURE --> FAILURE: Push retry failed

    PENDING --> SUCCESS: Push succeeded
    FAILURE --> SUCCESS: Push retry succeeded

    PENDING --> CANCELLED: Cancel RDP
    FAILURE --> CANCELLED: Cancel RDP

    SUCCESS --> CANCELLED: Staff Reset latest successful RDP

    note right of PENDING
        Open local RDP status.<br>
        New RDPs are created as PENDING.
        Deduplication does not change the local RDP status.
    end note

    note right of FAILURE
        Open retry status.<br>
        HOPE push workflow failed.
        Push can be retried.
        Cancel may be blocked while this RDP has a queued or running action.
    end note

    note right of SUCCESS
        Successful RDP status.<br>
        CW successfully completed the HOPE push.
        Related beneficiaries were marked as removed.
        Staff Reset can later move it to CANCELLED.
    end note

    note right of CANCELLED
        Cancelled RDP status.<br>
        No further RDP workflow actions are expected.
    end note
```

## Processing sequence

Most RDP actions are performed from the analyst workspace. Staff Reset is the only action shown here from the standard Django admin.

```mermaid
sequenceDiagram
    participant Staff as Staff Admin
    participant Analyst as Analyst Admin
    participant App as CW App
    participant DB as CW Database
    participant DE as DedupEngine
    participant HOPE as HOPE Core

    opt Optional: update dedup settings before RDP dedup starts
        Analyst->>App: Update dedup settings
        App->>DB: Check program can update DE settings
        Note over App,DB: Blocked after SUCCESS or while dedup is queued/running

        alt Update blocked
            App-->>Analyst: Show settings error
        else Update allowed
            App->>DE: Read current dedup settings
            Analyst->>App: Submit updated settings
            App->>DB: Recheck settings update is allowed
            App->>DE: Save updated dedup settings
            Note over App,DE: Program-level settings are updated before RDP dedup starts
        end
    end

    Analyst->>App: Create RDP
    App->>DB: Run RDP preflight checks

    alt Create blocked
        App-->>Analyst: Show create error
    else Create allowed
        App->>DB: Save RDP as PENDING
        Note over DB: New RDP starts as PENDING
    end

    opt Optional: run deduplication for biometric RDP
        Analyst->>App: Run deduplication
        App->>DB: Check dedup can start
        App->>DE: Create or process DS
        App->>DB: Append dedup operation log
        Note over DB: RDP status stays PENDING or FAILURE
    end

    Analyst->>App: Push or retry push
    App->>DB: Check push can start
    App->>HOPE: Recreate RDI for this push attempt
    App->>HOPE: Push beneficiaries
    App->>HOPE: Complete RDI

    alt Push failed
        App->>DB: Set FAILURE
        Note over DB: FAILURE remains retryable
    else Push succeeded
        App->>DB: Mark records removed and set SUCCESS
        App->>DE: Try approve DS if present
        Note over DB,DE: DE approval does not change local SUCCESS
    end

    opt Optional: cancel open RDP
        Analyst->>App: Cancel RDP
        App->>DB: Check cancel can start

        alt Cancel blocked
            App-->>Analyst: Show cancel error
        else Cancel allowed
            App->>DE: Reject DS if Deduplicated
            App->>DB: Set CANCELLED
            Note over DB: CANCELLED ends the local RDP workflow
        end
    end

    opt Optional: staff recovery after SUCCESS
        Staff->>App: Reset latest successful RDP
        App->>DB: Set related beneficiaries removed=False and set CANCELLED
        Note over Staff,DB: Staff Reset is a standard admin recovery action
    end
```

## Policy gates and side effects

```mermaid
flowchart TB
    subgraph SETTINGS["Update dedup settings"]
        S1["ALLOW: biometric program"]
        S2["BLOCK: SUCCESS RDP exists"]
        S3["BLOCK: dedup is queued or running"]
        S4["SAVE: program-level DE settings"]
    end

    subgraph CREATE["Create RDP"]
        C1["ALLOW: selection passes RDP preflight"]
        C2["BLOCK: empty selection or invalid records"]
        C3["BLOCK: records already linked to PENDING / FAILURE / SUCCESS RDP"]
        C4["BLOCK: biometric program cannot create a new DS"]
    end

    subgraph DEDUP["Deduplicate"]
        D1["ALLOW: biometric RDP is PENDING or FAILURE"]
        D2["BLOCK: dedup already queued/running for this RDP"]
        D3["RUN: create new DS or process existing READY DS"]
        D4["KEEP STATUS: PENDING or FAILURE"]
    end

    subgraph PUSH["Push to HOPE"]
        P1["ALLOW: RDP is PENDING or FAILURE"]
        P2["BLOCK: push already queued/running for this RDP"]
        P3["REQUIRE: Deduplicated DS for biometric push"]
        P4["SET: SUCCESS after completed HOPE push"]
        P5["SET: FAILURE when HOPE push fails"]
    end

    subgraph CANCEL["Cancel RDP"]
        X1["ALLOW: RDP is PENDING or FAILURE"]
        X2["BLOCK: push or dedup is queued/running"]
        X3["BLOCK: DE set is running"]
        X4["REJECT: DS only when Deduplicated"]
        X5["SET: CANCELLED"]
    end

    subgraph RESET["Staff Reset"]
        R1["ALLOW: latest successful RDP only"]
        R2["RESTORE: related beneficiaries removed=False"]
        R3["SET: CANCELLED"]
    end

    subgraph SERVICES["External services"]
        DE_API["DedupEngine<br>dedup settings, status, processing, approve/reject"]
        HOPE_API["HOPE Core<br>RDI lifecycle and beneficiary push"]
    end

    classDef rule fill:#F3F4F6,stroke:#6B7280,stroke-width:1.5px,color:#1F2937;
    classDef external fill:#FDECC8,stroke:#D18F00,stroke-width:1.5px,color:#5C4400;

    class S1,S2,S3,S4,C1,C2,C3,C4,D1,D2,D3,D4,P1,P2,P3,P4,P5,X1,X2,X3,X4,X5,R1,R2,R3 rule;
    class DE_API,HOPE_API external;
```

## Key rules

* `PENDING` and `FAILURE` are open local RDP statuses; `FAILURE` can be retried when policy allows it.
* Dedup settings can be updated only for biometric programs, before any successful RDP, and while no deduplication is queued or running.
* RDP preflight blocks empty selections, invalid records, and records already linked to another `PENDING`, `FAILURE`, or `SUCCESS` RDP.
* For biometric programs, RDP creation also requires DedupEngine to allow a new deduplication set.
* Deduplication is available only for biometric `PENDING` or `FAILURE` RDPs.
* Deduplication creates a new DedupEngine set or processes an existing `READY` set; it records an operation log entry but does not change the local RDP status.
* Push retry recreates the HOPE RDI for the current attempt.
* Biometric push requires the DedupEngine set to be `Deduplicated`.
* Successful push marks related beneficiaries as `removed=True`, stores the HOPE RDI id, and sets the RDP to `SUCCESS`.
* After successful push, CW tries to approve the DedupEngine set if present; approval failure is recorded but does not change local `SUCCESS`.
* Cancel is available only for open RDPs when no push, dedup, or running DedupEngine state blocks it.
* Cancel rejects the DedupEngine set only when the remote set is `Deduplicated`; otherwise it only cancels the local RDP.
* Staff Reset is available only for the latest `SUCCESS` RDP and moves it to `CANCELLED` after setting related beneficiaries `removed=False`.
