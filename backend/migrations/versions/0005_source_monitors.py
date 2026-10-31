"""Persist per-user regulatory source monitors.

Revision ID: 0005_source_monitors
Revises: 0004_compliance_status
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_source_monitors"
down_revision = "0004_compliance_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitored_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False, server_default="custom"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("poll_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("known_items", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_changes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_user_id", "url", name="uq_monitored_sources_owner_url"),
    )
    op.create_index("ix_monitored_sources_owner_enabled", "monitored_sources", ["owner_user_id", "enabled"])
    op.create_index("ix_monitored_sources_enabled", "monitored_sources", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_monitored_sources_enabled", table_name="monitored_sources")
    op.drop_index("ix_monitored_sources_owner_enabled", table_name="monitored_sources")
    op.drop_table("monitored_sources")
