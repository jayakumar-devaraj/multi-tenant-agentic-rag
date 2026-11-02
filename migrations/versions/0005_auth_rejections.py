"""Rejected requests (401, 403): a trail for calls that never reach a tenant's audit log (ADR 0002 addendum).

A 401 has no tenant to attach a row to, so these rows live outside the per-tenant `audit_log` and outside
row-level security. The app role may only INSERT; operators read the table with SQL. A row holds a
fingerprint of the presented credential, never the credential.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS auth_rejections (
            id          BIGSERIAL   PRIMARY KEY,
            ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
            status      SMALLINT    NOT NULL CHECK (status IN (401, 403)),
            reason      TEXT        NOT NULL,
            path        TEXT        NOT NULL,
            credential  TEXT        NOT NULL CHECK (credential IN ('none', 'static', 'jwt')),
            fingerprint TEXT,
            tenant_id   TEXT,
            client      TEXT,
            request_id  TEXT
        );
        CREATE INDEX IF NOT EXISTS auth_rejections_ts ON auth_rejections (ts DESC);
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS auth_rejections")
