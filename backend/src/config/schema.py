from src.config.database import engine
from sqlalchemy import inspect,text
LEGACY_COLUMNS=[('association_studies','revision','INT NOT NULL DEFAULT 0'),('association_runs','worksheet_revision','INT NULL DEFAULT NULL'),('verification_notes','worksheet_revision','INT NULL DEFAULT NULL')]

def ensure_columns():
 """create_all only creates missing tables; add revision columns to an existing
 demo schema so prior studies/runs/notes keep working without touching stored
 statistics."""
 with engine.begin() as conn:
  for table,column,ddl in LEGACY_COLUMNS:
   if not inspect(conn).has_table(table):continue
   existing={c['name'] for c in inspect(conn).get_columns(table)}
   if column not in existing:conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
  if inspect(conn).has_table('association_studies'):
   conn.execute(text('UPDATE association_studies SET revision=0 WHERE revision IS NULL'))
