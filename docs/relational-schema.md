# Relational Schema

This document defines the proposed canonical SQLite schema for the project. The structure is intentionally clean and multi-council ready, while keeping core entities normalized and keeping labels flexible for future classification.

## Design Goals

- One canonical person record per candidate
- Multi-council support from the start
- Temporal history for changes and validity windows
- Public-source traceability on records that originate from external pages
- Flexible labels for analysis and reporting without hard-coding every category

## Core Model

```mermaid
erDiagram
    COUNCILS ||--o{ PEOPLE : has
    COUNCILS ||--o{ PARTIES : has
    COUNCILS ||--o{ WARDS : has
    COUNCILS ||--o{ COMMITTEES : has
    COUNCILS ||--o{ MEETINGS : has
    COUNCILS ||--o{ ENTITY_LABELS : tags
    COUNCILS ||--o{ CHANGE_LOG : records
    COUNCILS ||--o{ PERSON_EVENTS : contains

    PEOPLE ||--o{ PERSON_EVENTS : participates_in
    PEOPLE ||--o{ CHANGE_LOG : audited_by

    PARTIES ||--o{ PERSON_EVENTS : related_to
    WARDS ||--o{ PERSON_EVENTS : scoped_by
    COMMITTEES ||--o{ MEETINGS : has
    MEETINGS ||--o{ PERSON_EVENTS : referenced_by

    EVENT_TYPES ||--o{ PERSON_EVENTS : classifies
    LABELS ||--o{ ENTITY_LABELS : assigned_to
    LABELS ||--o{ LABELS : groups
    PERSON_EVENTS ||--o{ PERSON_EVENT_LABELS : labeled_by
    LABELS ||--o{ PERSON_EVENT_LABELS : applies

    COUNCILS {
        int id PK
        string code
        string name
        text homepage_url
        datetime created_at
    }

    PEOPLE {
        int id PK
        int council_id FK
        string person_uid
        string canonical_name
        date first_seen_date
        text source_url
        date source_valid_from
        date source_valid_to
        datetime created_at
        datetime updated_at
    }

    PARTIES {
        int id PK
        int council_id FK
        string name
        string short_name
        text source_url
        date source_valid_from
        date source_valid_to
    }

    WARDS {
        int id PK
        int council_id FK
        string name
        string ward_code
        date valid_from
        date valid_to
        text source_url
    }

    EVENT_TYPES {
        int id PK
        string code
        string name
        text description
    }

    LABELS {
        int id PK
        int label_group_id FK
        string code
        string name
        text description
        bool is_group
    }

    ENTITY_LABELS {
        int id PK
        int council_id FK
        string entity_type
        string entity_key
        int label_id FK
        date valid_from
        date valid_to
        text source_url
        text notes
    }

    COMMITTEES {
        int id PK
        int council_id FK
        string title
        text public_url
        date first_held_date
        date valid_from
        date valid_to
    }

    MEETINGS {
        int id PK
        int council_id FK
        int committee_id FK
        string title
        date meeting_date
        text public_url
        date source_valid_from
        date source_valid_to
    }

    PERSON_EVENTS {
        int id PK
        int council_id FK
        int person_id FK
        int event_type_id FK
        int party_id FK
        int ward_id FK
        int committee_id FK
        int meeting_id FK
        text event_value
        text event_notes
        datetime changed_at
        date effective_from
        date effective_to
        text source_url
        date source_valid_from
        date source_valid_to
    }

    PERSON_EVENT_LABELS {
        int person_event_id PK, FK
        int label_id PK, FK
    }

    CHANGE_LOG {
        int id PK
        int council_id FK
        string table_name
        string record_id
        string field_name
        text old_value
        text new_value
        text change_reason
        string changed_by
        datetime changed_at
        text source_url
        date source_valid_from
        date source_valid_to
    }
```

## How the model is intended to work

- `people` holds one canonical person record per candidate/person identifier.
- `wards`, `parties`, and `committees` remain first-class entities because they have identity, dates, and relationships.
- `labels` is the flexible classification layer.
- `label_group_id` allows labels to be arranged into an N-tier hierarchy.
- `entity_labels` provides many-to-many tagging with validity windows, source links, and notes.
- `person_events` stores the change timeline for elections, councillor status, declarations, meetings, committee membership, surgery changes, absence reasons, and similar events.
- `change_log` records field-level updates for auditability and historic reporting.

## Seeded baseline data

The current initializer seeds:

- Birmingham City Council as the first council
- 9 event types
- 4 top-level label groups

## Initialization

```powershell
python scripts/init_database.py
```

The default SQLite file is `output/data/monitoring.sqlite`.

## Future expansion

This structure is designed to support future councils and alternative public data sources by adding another `councils` row and loading source-specific records under that council namespace.
