# RDP processing flow

This page shows how an **[RDP](index.md)** moves from creation through its configured **[RDP operations](operations/index.md)**, review, and the **[HOPE Core push](push.md)**.

For RDP status transitions, see **[Lifecycle and statuses](lifecycle.md)**.

## Processing sequence

```mermaid
sequenceDiagram
    participant User as Analyst / Collector
    participant CW as Country Workspace
    participant HD as Hope Documents
    participant DE as DedupEngine
    participant HOPE as HOPE Core

    User->>CW: Create RDP
    CW->>CW: Run preflight checks
    CW->>CW: Create RDP as PENDING

    opt RDP has configured operations
        par OCR
            opt OCR selected
                CW->>HD: Publish OCR requests via RabbitMQ
                HD-->>CW: Return OCR results via RabbitMQ
                CW->>CW: Store OCR findings
            end
        and Biometric deduplication
            opt Biometric deduplication configured
                CW->>DE: Create/resume set and upload photos
                DE-->>CW: Notify state change
                CW->>DE: Retrieve result and findings
                CW->>CW: Store biometric findings
            end
        and Biographic deduplication
            opt Biographic deduplication selected
                CW->>DE: Create/resume dataset and upload individuals
                DE-->>CW: Notify state change
                CW->>DE: Retrieve result and findings
                CW->>CW: Store biographic findings
            end
        end

        CW->>CW: Wait for all configured operations to reach SUCCESS
    end
    CW->>CW: Evaluate review thresholds

    alt Manual review required
        CW-->>User: REVIEW_PENDING

        alt Push all to HOPE
            User->>CW: Approve all findings
            CW->>CW: Set PUSH_PENDING
            CW->>HOPE: Prepare and push RDI
        else Create clean RDP
            User->>CW: Create clean replacement
            CW->>CW: Cancel source and create replacement as PENDING
            opt Biometric or biographic operation
                CW->>DE: Reject source sets
            end
            CW->>CW: Start replacement operations after required rejection
        else Cancel RDP
            User->>CW: Cancel RDP
        end
    else No review required
        CW->>CW: Set PUSH_PENDING
        CW->>HOPE: Prepare and push RDI
    end
```

## Operation processing

Only the selected operations are created with the RDP and run independently. **[OCR](operations/ocr.md)** sends identity documents to Hope Documents through RabbitMQ, while **[biometric](operations/biometric-deduplication.md)** and **[biographic](operations/biographic-deduplication.md)** deduplication use DedupEngine.

A technical operation failure leaves the RDP in `PENDING` and prevents it from continuing. Use **Retry operations** for failed or otherwise recoverable operations; the RDP is evaluated for the next step only after all configured operations reach `SUCCESS`.

See **[RDP operations](operations/index.md)** for the common operation lifecycle and recovery behavior.

## Findings and review

An operation can complete successfully while still producing findings.

After all configured operations succeed, Country Workspace evaluates each operation's review threshold independently. If any threshold is exceeded, the RDP moves to `REVIEW_PENDING`; otherwise the push starts automatically. If no operations are configured, push evaluation runs directly after RDP creation and the push starts without manual review.

From review, the user can push all beneficiaries, create a clean replacement RDP using selected operation findings, or cancel the RDP. See **[Review and Clean RDP](review.md)** for the complete decision flow.

## Push to HOPE Core

When the current RDP is approved to continue, it changes to `PUSH_PENDING`.

Country Workspace prepares HOPE Core, including any required previous-RDI reset, runs push preflight validation, creates a new RDI, sends the beneficiary data, and completes the RDI. A successful push changes the RDP to `SUCCESS`; a failed push attempt changes it to `FAILURE` and can be retried.

See **[Push to HOPE Core](push.md)** for the detailed push flow and **[Recover a stuck push](lifecycle.md#recover-a-stuck-push)** for recovery from an interrupted push.
