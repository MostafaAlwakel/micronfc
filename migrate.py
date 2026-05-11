"""
One-time migration script: safely adds new columns to store_orders.
Run with: python migrate.py
Safe to re-run — existing columns are skipped without error.
"""
from app import app
from models import db
from sqlalchemy import text, inspect


COLUMNS = [
    ("payment_method", "VARCHAR(50) DEFAULT 'card'"),
    ("tracking_number", "VARCHAR(10)"),
    # FK reference uses standard syntax; SQLite ignores FK constraints but accepts the column
    ("user_id",         'INTEGER REFERENCES "user"(id)'),
]


def column_exists(conn, table, column):
    insp = inspect(conn)
    cols = [c["name"] for c in insp.get_columns(table)]
    return column in cols


with app.app_context():
    with db.engine.connect() as conn:
        for col_name, col_def in COLUMNS:
            if column_exists(conn, "store_orders", col_name):
                print(f"  [skip]  {col_name} already exists")
                continue
            try:
                conn.execute(text(f"ALTER TABLE store_orders ADD COLUMN {col_name} {col_def}"))
                conn.commit()
                print(f"  [added] {col_name}")
            except Exception as e:
                conn.rollback()
                print(f"  [error] {col_name}: {e}")

    # Create any brand-new tables (won't touch existing ones)
    db.create_all()
    print("\nMigration complete.")
