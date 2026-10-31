"""Add L2 internal repository and impact management.

Revision ID: 0006_l2_impact_management
Revises: 0005_source_monitors
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_l2_impact_management"
down_revision = "0005_source_monitors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "internal_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_type", sa.String(40), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("department", sa.String(160)),
        sa.Column("owner_name", sa.String(240)),
        sa.Column("system_name", sa.String(240)),
        sa.Column("criticality", sa.String(24), nullable=False, server_default="medium"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_internal_assets_owner_type", "internal_assets", ["owner_user_id", "asset_type"])
    op.create_index("ix_internal_assets_owner_department", "internal_assets", ["owner_user_id", "department"])

    op.create_table(
        "impact_assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_version_id", sa.String(36), sa.ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_impact_assessments_owner_created", "impact_assessments", ["owner_user_id", "created_at"])

    op.create_table(
        "impact_mappings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("assessment_id", sa.String(36), sa.ForeignKey("impact_assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("obligation_id", sa.String(36), sa.ForeignKey("obligations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("internal_asset_id", sa.String(36), sa.ForeignKey("internal_assets.id", ondelete="SET NULL")),
        sa.Column("gap_status", sa.String(32), nullable=False, server_default="not_addressed"),
        sa.Column("match_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("reviewed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("assessment_id", "obligation_id", "internal_asset_id", name="uq_impact_mapping_pair"),
    )
    op.create_index("ix_impact_mappings_assessment_status", "impact_mappings", ["assessment_id", "gap_status"])

    op.create_table(
        "recommendations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("impact_mapping_id", sa.String(36), sa.ForeignKey("impact_mappings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("draft_wording", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending_review"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_recommendations_mapping", "recommendations", ["impact_mapping_id"])

    op.create_table(
        "remediation_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assessment_id", sa.String(36), sa.ForeignKey("impact_assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("impact_mapping_id", sa.String(36), sa.ForeignKey("impact_mappings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recommendation_id", sa.String(36), sa.ForeignKey("recommendations.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("owner_name", sa.String(240)),
        sa.Column("department", sa.String(160)),
        sa.Column("due_date", sa.Date()),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_remediation_actions_owner_status", "remediation_actions", ["owner_user_id", "status"])
    op.create_index("ix_remediation_actions_assessment", "remediation_actions", ["assessment_id"])

    op.create_table(
        "assessment_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("assessment_id", sa.String(36), sa.ForeignKey("impact_assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assessment_events_assessment", "assessment_events", ["assessment_id", "created_at"])


def downgrade() -> None:
    op.drop_table("assessment_events")
    op.drop_index("ix_remediation_actions_assessment", table_name="remediation_actions")
    op.drop_index("ix_remediation_actions_owner_status", table_name="remediation_actions")
    op.drop_table("remediation_actions")
    op.drop_index("ix_recommendations_mapping", table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_index("ix_impact_mappings_assessment_status", table_name="impact_mappings")
    op.drop_table("impact_mappings")
    op.drop_index("ix_impact_assessments_owner_created", table_name="impact_assessments")
    op.drop_table("impact_assessments")
    op.drop_index("ix_internal_assets_owner_department", table_name="internal_assets")
    op.drop_index("ix_internal_assets_owner_type", table_name="internal_assets")
    op.drop_table("internal_assets")
