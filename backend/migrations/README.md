# Initial schema
SQLAlchemy metadata.create_all initializes the five business tables plus users and audit on first start. Unique keys: study.code, (stratum.study_id,stratum.code), count.stratum_id, run.name, note.title. Foreign keys form study→stratum→count and study→run→note. This is not a production schema migration mechanism; use a versioned migration tool before evolving persisted deployments.

## Worksheet versioning columns
When a deployed demo database predates version tracking, startup runs `src/config/schema.ensure_columns()` after `create_all`. It adds, only when absent:

- `association_studies.revision INT NOT NULL DEFAULT 0`
- `association_runs.worksheet_revision INT NULL`
- `verification_notes.worksheet_revision INT NULL`

It never alters stored `result`, `input_snapshot` or note content. Unversioned legacy runs are classified stale by comparing their frozen content with the current worksheet. For real deployments, express the same change as a versioned migration (e.g. Alembic) instead of relying on this compatibility step.
