# hope-country-workspace

## Spreadsheet import

```mermaid
---
title: Spreadsheet import or validation
---
graph TD
;
    A[Upload file] --> B{Import or validate?}
    B -- Import --> C[Save valid records]
    C --> D{Is there invalid records?}
    D -- Yes --> E[Generate error report]
    E --> F[Generate file with invalid records]
    F --> G[End]
    D -- No --> G
    
    B -- Validate --> H{Is there invalid records?}
    H -- No --> G
    H -- Yes --> I[Generate error report]
    I --> G
```

**TBD**:
- Previous import error report could be displayed on spreadsheet entry page.
- Do we need to save data from previous import attempt if we still have to parse
  each row on every import attempt?
- Do we need to display errors from previous import attempt on spreadsheet entry
  page?

```mermaid
---
title: Table structure
---
erDiagram
    Program ||--o{ Spreadsheet: has
    Program ||--o{ Individual: has
    Program ||--o{ Household: has
    Spreadsheet ||--o{ SpreadsheetIndividual: has
    SpreadsheetIndividual }o--|| Individual: is
    Spreadsheet ||--o{ SpreadsheetHousehold: has
    SpreadsheetHousehold }o--|| Household: is
```

## Kobo Import

```mermaid
---
title: Dataset import
---
graph TD
;
    A[Fetch dataset] --> B{All records are valid?}
    B -- Yes --> C[Save all records]
    C --> D[End]
    B -- No --> E[Generate error report]
    E --> D
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

    Program ||--o{ Dataset: has
    Program ||--o{ Individual: has
    Program ||--o{ Household: has
    Dataset ||--o{ DatasetIndividual: has
    DatasetIndividual }o--|| Individual: is
    Dataset ||--o{ DatasetHousehold: has
    DatasetHousehold }o--|| Household: is
```

**TBD:**

- Dataset format
- Do we need to display errors from previous import attempt on dataset entry page?

## Aurora Import

## HOPE export

**TBD**:

- When deduplication is run in Country Workspace?
