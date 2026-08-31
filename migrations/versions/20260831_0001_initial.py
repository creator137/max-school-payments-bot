"""Initial school payment schema."""

import sqlalchemy as sa
from alembic import op

revision = "20260831_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("max_user_id", sa.BigInteger(), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("link_code", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("max_user_id"),
        sa.UniqueConstraint("link_code"),
    )
    op.create_index("ix_parents_max_user_id", "parents", ["max_user_id"], unique=True)
    op.create_index("ix_parents_link_code", "parents", ["link_code"], unique=True)
    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
    )
    op.create_table(
        "user_states",
        sa.Column("max_user_id", sa.BigInteger(), primary_key=True),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("data", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "children",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("parents.id"), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_children_parent_id", "children", ["parent_id"])
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("child_id", sa.Integer(), sa.ForeignKey("children.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("monthly_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("child_id", "subject_id"),
    )
    op.create_index("ix_subscriptions_child_id", "subscriptions", ["child_id"])
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("child_id", sa.Integer(), sa.ForeignKey("children.id"), nullable=False),
        sa.Column("billing_month", sa.String(7), nullable=False),
        sa.Column("expected_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "receipt_received",
                "paid",
                "rejected",
                name="paymentstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manual", sa.Boolean(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("child_id", "billing_month"),
    )
    op.create_index("ix_payments_child_id", "payments", ["child_id"])
    op.create_index("ix_payments_billing_month", "payments", ["billing_month"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_table(
        "receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=True),
        sa.Column("content_type", sa.String(120), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("max_attachment_token", sa.String(512), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_receipts_payment_id", "receipts", ["payment_id"])
    op.create_table(
        "reminder_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("reminder_day", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("payment_id", "reminder_day"),
    )
    op.create_index("ix_reminder_logs_payment_id", "reminder_logs", ["payment_id"])


def downgrade() -> None:
    for table in [
        "reminder_logs",
        "receipts",
        "payments",
        "subscriptions",
        "children",
        "user_states",
        "subjects",
        "parents",
    ]:
        op.drop_table(table)
