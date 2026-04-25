"""
Shared constants for the OpenClaw agent fleet.

Single source of truth for:
- Schema / domain / agent identifiers
- Pipeline timeouts (used by qr_monitor)
- Backtest / risk / QA / data-validator tuning knobs
- Variant generation + flood-control limits

All thresholds that get tuned at runtime (risk + QA gates) live in the
`risk_config` table and are loaded by the agents at runtime.
The values here are operational, not strategy-evaluation, knobs.
"""

# ─── Schema / domains ───────────────────────────────────────────────────────
SCHEMA = "openclaw_researcher"
QUANT_DOMAIN = "quant"
PLATFORM_DOMAIN = "platform"

# ─── Agent identifiers (must match routing_rules.target_agent and AGENT_SESSIONS) ──
AGENT_HUB = "qr_hub"
AGENT_MONITOR = "qr_monitor"
AGENT_DATA_VALIDATOR = "qr_data_validator"
AGENT_ALGO = "qr_algo"
AGENT_RISK = "qr_risk"
AGENT_QA = "qr_qa"
AGENT_DEBATE = "qr_debate"
AGENT_EXP_MANAGER = "qr_exp_manager"
AGENT_IDEA_INTAKE = "qr_idea_intake"
AGENT_ETL_MANAGER = "qr_etl_manager"
AGENT_RESEARCHER = "qr_researcher"
AGENT_MACRO_SENTINEL = "qr_macro_sentinel"
AGENT_ARCHITECT = "qr_architect"

# ─── Pipeline timeouts (minutes) — used by qr_monitor ──────────────────────
# An event "in flight" longer than this triggers re-queue or escalation.
TIMEOUT_THRESHOLDS = {
    "experiment.started": 15,
    "dataset.ready":      10,
    "backtest.completed": 30,
    "risk.evaluated":      5,
    "debate.completed":    5,
    "qa.validated":        5,
}

# Gold-layer lock auto-clear (hours). Read by qr_monitor on every cycle.
GOLD_LAYER_LOCK_TIMEOUT_HOURS = 12

# ─── Backtest engine knobs (qr_algo) ───────────────────────────────────────
BACKTEST_TIMEOUT_MINUTES = 30
BACKTEST_IS_OOS_SPLIT    = 0.70   # 70% IS / 30% OOS
TRANSACTION_COST_PCT     = 0.0005  # 5 bps round-trip
RISK_FREE_RATE           = 0.04    # annualised
ANNUALISATION_FACTOR     = 252     # daily bars

# ─── Risk scoring weights / thresholds (qr_risk) ───────────────────────────
# Note: actual gate values live in `risk_config`; these are scoring knobs only.
RISK_APPROVAL_THRESHOLD   = 0.34   # score below this → approved
RISK_BORDERLINE_THRESHOLD = 0.50   # score between approval and borderline → flagged but allowed
RISK_WEIGHT_MAX_DRAWDOWN     = 1.0
RISK_WEIGHT_SHARPE_OOS       = 1.0
RISK_WEIGHT_SHARPE_RATIO     = 1.0
RISK_WEIGHT_HIGH_TURNOVER    = 0.5
RISK_WEIGHT_LOW_TRADE_COUNT  = 1.0

# ─── Data validator knobs (qr_data_validator) ──────────────────────────────
DE_MISSING_BAR_TOLERANCE   = 0.10  # 10% missing bars max
DE_PRICE_SPIKE_STDDEV      = 5.0   # 5σ flagged as spike
DE_MIN_HISTORY_MULTIPLIER  = 2.0   # need ≥ 2× lookback_window of pre-history
MAX_RETRY_COUNT            = 2     # validator retries before workflow.stuck

# ─── Idea intake (qr_idea_intake) ──────────────────────────────────────────
MAX_INTAKE_IN_PROGRESS = 10  # flood-control limit for human-submitted ideas

# ─── Experiment manager (qr_exp_manager) ───────────────────────────────────
FLOOD_CONTROL_LIMIT     = 50    # max in-flight experiments before exp_manager pauses
MAX_VARIANTS_PER_CYCLE  = 5

# Phase 1 = directed mutations on first-generation experiments
EXP_PHASE1_THRESHOLD       = 0.6   # conviction/score above this → wider variant search
EXP_PHASE1_VARIANTS_PASS   = 3     # variants generated when QA passes
EXP_PHASE1_VARIANTS_FAIL   = 2     # variants when QA fails (directed mutation)
# Phase 2 = nightly seeding from top performers
EXP_PHASE2_VARIANTS        = 5

EXP_DUPLICATE_LOOKBACK_DAYS = 30   # don't re-run identical param_set within this window
EXP_PRUNE_PASS_RATE         = 0.05 # family pass rate below 5% → prune
EXP_EXPAND_PASS_RATE        = 0.30 # family pass rate above 30% → expand
EXP_PRUNE_MIN_EXPERIMENTS   = 20   # need ≥ 20 experiments before pruning a family

# Nightly cycle (00:00 SGT) tuning
EXP_NIGHTLY_TOP_SHARPE     = 0.5   # only seed from strategies with sharpe_oos above this
EXP_NIGHTLY_LOOKBACK_DAYS  = 7
EXP_NIGHTLY_FALLBACK_COUNT = 3     # if no top performers, seed N random experiments

# Variant parameter ranges (used for ±N% mutations)
PARAM_LOOKBACK_MIN = 5
PARAM_LOOKBACK_MAX = 200
PARAM_ENTRY_MIN    = 0.5
PARAM_ENTRY_MAX    = 3.0
PARAM_EXIT_MIN     = 0.5
PARAM_EXIT_MAX     = 3.0
