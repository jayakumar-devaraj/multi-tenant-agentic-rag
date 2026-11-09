"""Per-tenant request counters for rate limits, shared by every API replica (ADR 0003).

One row per tenant, action and one-minute window; the API increments it atomically and deletes the
tenant's older windows as it goes. Row-level security confines each connection to its tenant's rows.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TENANT = "tenant_id = current_setting('app.tenant_id', true)"


def upgrade() -> None:
    bind = op.get_bind()
    for statement in (
        """
        CREATE TABLE IF NOT EXISTS tenant_usage (
            tenant_id    TEXT        NOT NULL,
            action       TEXT        NOT NULL CHECK (action IN ('query', 'ingest')),
            window_start TIMESTAMPTZ NOT NULL,
            count        INTEGER     NOT NULL,
            PRIMARY KEY (tenant_id, action, window_start)
        )
        """,
        "ALTER TABLE tenant_usage ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE tenant_usage FORCE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS tenant_isolation ON tenant_usage",
        f"CREATE POLICY tenant_isolation ON tenant_usage USING ({TENANT}) WITH CHECK ({TENANT})",
    ):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS tenant_usage")
