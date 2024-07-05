# hope-country-workspace

## Spreadsheet import

```mermaid
---
title: Spreadsheet import
---
graph TD
;
    A[Upload file] --> B{All records are valid?}
    B -- Yes --> E[End]
    B -- No --> C[Generate error report]
    C --> D[Clear imported records]
    D --> A
```

Previous import error report could be displayed on spreadsheet entry page.

**TBD**:

- Do we need to save data from previous import attempt if we still have to parse
  each row on every import attempt?
- Should we add a flag to show data from spreadsheet is ready for export to HOPE?
- Do we need to display errors from previous import attempt on spreadsheet entry
  page?

```mermaid
---
title: Table structure
---
erDiagram
    Spreadsheet {
        string title
    }
    
    Error {
        string sheet
        int row
        string column
    }
    
    Program ||--o{ Spreadsheet: has
    Program ||--o{ Individual: has
    Program ||--o{ Household: has
    Program ||--o{ IndividualRoleInHousehold: has

    Spreadsheet ||--o{ IndividualRecord: has
    IndividualRecord }o--|| Individual: is
    Spreadsheet ||--o{ HouseholdRecord: has
    HouseholdRecord }o--|| Household: is
    Spreadsheet ||--o{ IndividualRoleRecord: has
    IndividualRoleRecord ||--o{ IndividualRoleInHousehold: is
    Spreadsheet ||--o{ Error: has
```

## Kobo Import

```mermaid
---
title: Dataset import
---
graph TD
;
    A[Fetch dataset] --> B{All records are valid?}
    B -- Yes --> E[End]
    B -- No --> C[Generate error report]
    C --> D[Clear imported records]
    D --> A
```

```mermaid
---
title: Table structure
---
erDiagram
    Dataset {
        string title
        string url
    }
    
    Error {
        string data
    }
    
    Program ||--o{ Dataset: has
    Program ||--o{ Individual: has
    Program ||--o{ Household: has
    Program ||--o{ IndividualRoleInHousehold: has
 
    Dataset ||--o{ IndividualRecord: has
    IndividualRecord }o--|| Individual: is
    Dataset ||--o{ HouseholdRecord: has
    HouseholdRecord }o--|| Household: is
    Dataset ||--o{ IndividualRoleRecord: has
    IndividualRoleRecord ||--o{ IndividualRoleInHousehold: is
    Dataset ||--o{ Error: has
```

**TBD:**
- Dataset format
- Do we need to display errors from previous import attempt on dataset entry page?

## Aurora Import

## HOPE export

**TBD**:

- When deduplication is run in Country Workspace?
