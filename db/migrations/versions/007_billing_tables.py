"""FinOps billing tables and tenant credit balance.

Revision ID: 007
Revises: 006
Create Date: 2026-04-26

Changes
-------
1. Create ``model_pricing`` table — per-model USD rates (seeded with
   common OpenAI and Anthropic models).

2. Create ``billing_events`` table — immutable per-LLM-call cost records.

3. Add two columns to ``tenants``:
   - ``credit_balance`` NUMERIC(12,6) NULL  — prepaid credit in USD;
     NULL = unlimited (backward-compat default for existing tenants).
   - ``total_cost_usd``  NUMERIC(12,6) NOT NULL DEFAULT 0 — running
     all-time API spend (informational counter).

Pricing seed data (USD per 1 million tokens, as of 2026-04):
  OpenAI   gpt-4o               $5.00 in  / $15.00 out
  OpenAI   gpt-4o-mini          $0.15 in  / $0.60  out
  OpenAI   gpt-4.1              $2.00 in  / $8.00  out
  OpenAI   gpt-4.1-mini         $0.40 in  / $1.60  out
  Anthropic claude-opus-4       $15.00 in / $75.00 out
  Anthropic claude-sonnet-4     $3.00 in  / $15.00 out
  Anthropic claude-haiku-4      $0.80 in  / $4.00  out
  DeepSeek  deepseek-chat       $0.27 in  / $1.10  out
  DeepSeek  deepseek-reasoner   $0.55 in  / $2.19  out
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

_NOW = datetime.now(timezone.utc).isoformat()


def upgrade() -> None:
    # ── 1. model_pricing ─────────────────────────────────────────────────────
    op.create_table(
        "model_pricing",
        sa.Column("model_id",            sa.String(128),      primary_key=True),
        sa.Column("provider",            sa.String(50),       nullable=False),
        sa.Column("input_price_per_1m",  sa.Numeric(10, 6),   nullable=False),
        sa.Column("output_price_per_1m", sa.Numeric(10, 6),   nullable=False),
        sa.Column("is_active",           sa.Boolean(),         nullable=False, server_default="true"),
        sa.Column("updated_at",          sa.String(50),        nullable=False),
    )

    # ── 2. billing_events ─────────────────────────────────────────────────────
    op.create_table(
        "billing_events",
        sa.Column("id",                sa.Integer(),       primary_key=True, autoincrement=True),
        sa.Column("tenant_id",         sa.String(36),      nullable=False),
        sa.Column("job_id",            sa.String(8),       nullable=True),
        sa.Column("model_id",          sa.String(128),     nullable=False),
        sa.Column("prompt_tokens",     sa.Integer(),       nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(),       nullable=False, server_default="0"),
        sa.Column("cost_usd",          sa.Numeric(12, 8),  nullable=False, server_default="0"),
        sa.Column("created_at",        sa.String(50),      nullable=False),
    )
    op.create_index("ix_billing_events_tenant_id", "billing_events", ["tenant_id"])
    op.create_index("ix_billing_events_job_id",    "billing_events", ["job_id"])

    # ── 3. tenants: credit_balance + total_cost_usd ───────────────────────────
    op.add_column("tenants", sa.Column(
        "credit_balance", sa.Numeric(12, 6), nullable=True,
    ))
    op.add_column("tenants", sa.Column(
        "total_cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0",
    ))

    # ── 4. Seed pricing data ──────────────────────────────────────────────────
    pricing = op.get_bind()
    pricing.execute(sa.text("""
        INSERT INTO model_pricing
            (model_id, provider, input_price_per_1m, output_price_per_1m, is_active, updated_at)
        VALUES
            -- OpenAI
            ('gpt-4o',                   'openai',    5.000000, 15.000000, true, :ts),
            ('gpt-4o-2024-08-06',        'openai',    2.500000, 10.000000, true, :ts),
            ('gpt-4o-mini',              'openai',    0.150000,  0.600000, true, :ts),
            ('gpt-4o-mini-2024-07-18',   'openai',    0.150000,  0.600000, true, :ts),
            ('gpt-4.1',                  'openai',    2.000000,  8.000000, true, :ts),
            ('gpt-4.1-mini',             'openai',    0.400000,  1.600000, true, :ts),
            ('o1',                       'openai',   15.000000, 60.000000, true, :ts),
            ('o1-mini',                  'openai',    3.000000, 12.000000, true, :ts),
            ('o3-mini',                  'openai',    1.100000,  4.400000, true, :ts),
            -- Anthropic
            ('claude-opus-4-20250514',   'anthropic', 15.000000, 75.000000, true, :ts),
            ('claude-opus-4-5',          'anthropic', 15.000000, 75.000000, true, :ts),
            ('claude-sonnet-4-20250514', 'anthropic',  3.000000, 15.000000, true, :ts),
            ('claude-sonnet-4-6',        'anthropic',  3.000000, 15.000000, true, :ts),
            ('claude-haiku-4-5-20251001','anthropic',  0.800000,  4.000000, true, :ts),
            -- DeepSeek
            ('deepseek-chat',            'deepseek',   0.270000,  1.100000, true, :ts),
            ('deepseek-reasoner',        'deepseek',   0.550000,  2.190000, true, :ts),
            -- GLM / Zhipu
            ('glm-4.7',                  'zhipu',      0.100000,  0.400000, true, :ts),
            ('glm-5',                    'zhipu',      0.700000,  2.800000, true, :ts)
        ON CONFLICT (model_id) DO NOTHING
    """), {"ts": _NOW})


def downgrade() -> None:
    op.drop_column("tenants", "total_cost_usd")
    op.drop_column("tenants", "credit_balance")
    op.drop_index("ix_billing_events_job_id",    table_name="billing_events")
    op.drop_index("ix_billing_events_tenant_id", table_name="billing_events")
    op.drop_table("billing_events")
    op.drop_table("model_pricing")
