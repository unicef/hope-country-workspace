# Data Model

This diagram represents the core data model for the Country Workspace system, which manages beneficiary data import, processing, and export to HOPE Core.

**Key Components:**

**Flex Fields System (ff_*)** - Configurable field definitions and validation rules:

- `ff_DATACHECKER` - Validation rules for data quality
- `ff_FIELDSET` - Groups of related fields
- `ff_FLEXFIELD` - Individual flexible field definitions
- `ff_FIELDDEFINITION` - Field type definitions and constraints

**Core Entities** - Main business objects:

- `OFFICE` - Organizational units managing programs
- `PROGRAM` - Aid programs with specific beneficiary groups
- `BATCH` - Import containers for beneficiary data
- `HOUSEHOLD` / `INDIVIDUAL` - Core beneficiary records with flexible fields
- `RDP` - Export containers for pushing data to HOPE
- `DATASERIALIZER` - Serialization logic for data transformation
- `MAPPINGIMPORTER` - Contains mapping rules applied during data import
- `ASYNCJOB` - Background job processing for system operations

The system supports flexible data schemas through the ff_* entities, allowing different programs to define custom fields and validation rules for their specific beneficiary data requirements. Import processing is handled through configurable mapping rules that transform incoming data to match program requirements.

```mermaid

erDiagram
    ff_DATACHECKER {
        int id PK
        varchar name UK
        text description
    }

    ff_FIELDDEFINITION {
        int id PK
        varchar name UK
        text description
        jsonb attrs
        varchar field_type
        varchar slug UK
        bool validated
    }

    ff_FIELDSET {
        int id PK
        varchar name UK
        text description
        int extends_id FK
    }

    ff_FLEXFIELD {
        int id PK
        varchar name
        text description
        jsonb attrs
        varchar slug
        int definition_id FK
        int fieldset_id FK
        int master_id FK
    }

    DATASERIALIZER {
        int id PK
        varchar name UK
        text code
    }

    OFFICE {
        int id PK
        varchar hope_id UK
        varchar name
        varchar code UK
        varchar slug UK
    }

    USER {
        int id PK
        varchar username UK
    }

    BENEFICIARYGROUP {
        int id PK
        varchar name UK
        bool master_detail
    }

    PROGRAM {
        int id PK
        varchar hope_id UK
        varchar name
        varchar status
        int country_office_id FK
        int beneficiary_group_id FK
        int household_checker_id FK
        int individual_checker_id FK
        int serializer_id FK
    }

    BATCH {
        int id PK
        varchar name
        int imported_by_id FK
        int country_office_id FK
        int program_id FK
    }

    HOUSEHOLD {
        int id PK
        varchar name
        int batch_id FK
        jsonb flex_fields
        bytea flex_files
    }

    INDIVIDUAL {
        int id PK
        varchar name
        int batch_id FK
        int household_id FK
        jsonb flex_fields
        bytea flex_files
    }

    RDP {
        int id PK
        varchar name
        varchar status
        int country_office_id FK
        int program_id FK
        int pushed_by_id FK
    }

    MAPPINGIMPORTER {
        int id PK
        varchar name
        int data_checker_id FK
    }

    ASYNCJOB {
        int id PK
        int owner_id FK
        int batch_id FK
        int program_id FK
        int rdp_id FK
    }

    %% Relationships
    ff_DATACHECKER ||--o{ ff_FIELDSET : "contains"
    ff_FIELDSET ||--o{ ff_FIELDSET : "extends"
    ff_FIELDSET ||--o{ ff_FLEXFIELD : "contains"
    ff_FIELDDEFINITION ||--o{ ff_FLEXFIELD : "defines"
    ff_FLEXFIELD ||--o{ ff_FLEXFIELD : "master"

    ff_DATACHECKER ||--o{ PROGRAM : "validates_household"
    ff_DATACHECKER ||--o{ PROGRAM : "validates_individual"
    ff_DATACHECKER ||--|| MAPPINGIMPORTER : "attached_to"

    OFFICE ||--o{ PROGRAM : "manages"
    OFFICE ||--o{ BATCH : "imports_via"
    OFFICE ||--o{ RDP : "pushes_via"

    USER ||--o{ BATCH : "imports"
    USER ||--o{ RDP : "pushes"
    USER ||--o{ ASYNCJOB : "owns"

    BENEFICIARYGROUP ||--o{ PROGRAM : "categorizes"
    HOUSEHOLD ||--o{ INDIVIDUAL : "contains"

    PROGRAM ||--|| DATASERIALIZER : "uses"
    PROGRAM ||--o{ BATCH : "contains"
    PROGRAM ||--o{ RDP : "pushes_to"
    PROGRAM ||--o{ ASYNCJOB : "processes"

    BATCH ||--o{ HOUSEHOLD : "contains"
    BATCH ||--o{ INDIVIDUAL : "contains"
    BATCH ||--o{ ASYNCJOB : "processes"

    RDP ||--o{ HOUSEHOLD : "contains"
    RDP ||--o{ INDIVIDUAL : "contains"
    RDP ||--o{ ASYNCJOB : "processes"


```
