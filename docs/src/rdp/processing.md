# RDP processing flow

This page shows how Country Workspace interacts with DedupEngine and HOPE Core during RDP processing.

For RDP status definitions and transitions, see **[Statuses](lifecycle.md#statuses)** and **[RDP state flow](lifecycle.md#rdp-state-flow)**.

## Processing sequence
```mermaid
sequenceDiagram
    participant Workspace as Analyst / Collector Workspace
    participant CW as Country Workspace
    participant DE as DedupEngine
    participant HOPE as HOPE Core

    Workspace->>CW: Create RDP
    CW->>CW: Run preflight checks
    CW->>CW: Create RDP as PENDING

    opt Biometric deduplication
        Workspace->>CW: Deduplicate
        CW->>DE: Create or process Deduplication Set
        Note over CW,DE: RDP status remains unchanged
        Note over CW,DE: Push remains unavailable until the set reaches Deduplicated
    end

    Workspace->>CW: Push or retry push
    CW->>CW: Set PUSH_PENDING

    opt RDP is linked to a previous HOPE RDI
        CW->>HOPE: Request RDI reset

        alt Reset accepted or outcome unconfirmed
            Note over CW,HOPE: RDP remains PUSH_PENDING while waiting for HOPE readiness

            opt HOPE confirms readiness
                HOPE-->>CW: Confirm RDI readiness
            end
        else Previous RDI not found
            Note over CW,HOPE: Continue with a new RDI
        else Previous RDI already merged
            CW->>CW: Mark applicable RDP records removed
            CW->>CW: Set SUCCESS

            opt Biometric RDP
                CW->>DE: Approve Deduplication Set
                Note over CW,DE: Approval failure does not change SUCCESS
            end
        else RDI merge in progress
            CW->>CW: Set FAILURE
        end
    end

    opt Data push can proceed
        CW->>CW: Run preflight checks

        alt Preflight fails
            CW->>CW: Set FAILURE
        else Preflight passes
            alt RDI creation and data push succeed
                CW->>HOPE: Create new RDI

                alt Household-based Program
                    CW->>HOPE: Send Individuals
                    CW->>HOPE: Send Households
                else People-only Program
                    CW->>HOPE: Send People
                end

                CW->>HOPE: Complete RDI
                CW->>CW: Mark applicable RDP records removed
                CW->>CW: Set SUCCESS

                opt Biometric RDP
                    CW->>DE: Approve Deduplication Set
                    Note over CW,DE: Approval failure does not change SUCCESS
                end
            else RDI creation or data push fails
                CW->>CW: Set FAILURE
            end
        end
    end
```

## Related documentation

See **[Create the RDP](create.md#create-the-rdp)** for RDP creation and preflight checks, **[Run deduplication](deduplication.md#run-deduplication)** for biometric processing, and **[Start the push](push.md#start-the-push)** for the standard HOPE push flow.

For an RDP linked to a previous HOPE RDI, see **[Retry a failed push](push.md#retry-a-failed-push)** for the RDI reset and retry flow.

For lifecycle operations outside the normal processing sequence, see **[Cancel an RDP](lifecycle.md#cancel-an-rdp)** and **[Staff Reset](lifecycle.md#staff-reset)**.
