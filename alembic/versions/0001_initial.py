# -*- coding: utf-8 -*-
"""Начальная схема: кэш офферов, кампании, потоки, привязки офферов."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kt_offer_cache",
        sa.Column("kt_offer_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("affiliate_network_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "campaigns",
        sa.Column("kt_campaign_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("alias", sa.String(), nullable=False),
        sa.Column("created_via_wrapper", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "streams",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kt_stream_id", sa.Integer(), nullable=False),
        sa.Column("kt_campaign_id", sa.Integer(),
                  sa.ForeignKey("campaigns.kt_campaign_id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_offer_stream", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("dirty", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("warning", sa.String(), nullable=True),
        sa.Column("published_offers", sa.JSON(), nullable=False),
        sa.Column("kt_meta", sa.JSON(), nullable=False),
    )
    op.create_index("ix_streams_kt_stream_id", "streams", ["kt_stream_id"], unique=True)
    op.create_index("ix_streams_kt_campaign_id", "streams", ["kt_campaign_id"])
    op.create_table(
        "offer_bindings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stream_id", sa.Integer(), sa.ForeignKey("streams.id"), nullable=False),
        sa.Column("kt_offer_id", sa.Integer(), nullable=False),
        sa.Column("share", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("added_unpushed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("stream_id", "kt_offer_id", name="uq_stream_offer"),
    )
    op.create_index("ix_offer_bindings_stream_id", "offer_bindings", ["stream_id"])
    op.create_index("ix_offer_bindings_kt_offer_id", "offer_bindings", ["kt_offer_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_bindings_kt_offer_id", table_name="offer_bindings")
    op.drop_index("ix_offer_bindings_stream_id", table_name="offer_bindings")
    op.drop_table("offer_bindings")
    op.drop_index("ix_streams_kt_campaign_id", table_name="streams")
    op.drop_index("ix_streams_kt_stream_id", table_name="streams")
    op.drop_table("streams")
    op.drop_table("campaigns")
    op.drop_table("kt_offer_cache")
