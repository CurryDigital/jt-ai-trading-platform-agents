#!/bin/bash
# Daily Data Refresh Script - Medallion Architecture
# Updated: 2026-03-21 - Added Binance crypto, removed Yahoo crypto
# Runs: Bronze → Silver → Gold → Consumption

set -e

WORKSPACE="/home/ubuntu/.openclaw/workspace/quant_research"
LOG_FILE="$WORKSPACE/agents/etl/logs/daily_refresh_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$WORKSPACE/agents/etl/logs"

exec 1>>"$LOG_FILE" 2>&1

echo "=========================================="
echo "DAILY REFRESH STARTED: $(date)"
echo "Workspace: $WORKSPACE"
echo "=========================================="

export PYTHONPATH="$WORKSPACE:$PYTHONPATH"
export AWS_REGION="ap-southeast-1"

# Load environment variables
set -a && source ~/.openclaw/.env && set +a

# Ensure packages are installed
echo "Checking Python dependencies..."
pip3 install --break-system-packages pandas yfinance requests python-dotenv 2>/dev/null || true

cd "$WORKSPACE/agents/etl"

# ─────────────────────────────────────────────
echo ""
echo "🔶 BRONZE — Raw Ingestion (by Source System)"
echo "------------------------------------------"

# Binance (crypto) - PRIMARY crypto source
echo "→ Binance (crypto)..."
if [ -f "bronze/binance/crypto_ingest.py" ]; then
    python3 bronze/binance/crypto_ingest.py || echo "⚠️ Binance crypto failed"
fi

# NOTE: Coinbase disabled - using Binance as primary crypto source
# Coinbase remains available in bronze/coinbase/ if needed in future
# Reasons: JWT auth complexity, lower rate limits vs Binance

# FMP (equities/fundamentals)
echo "→ FMP..."
for f in bronze/fmp/*.py; do
  [ -f "$f" ] && python3 "$f" || true
done

# Interactive Brokers (positions/portfolio + live TWS sync)
echo "→ IBKR..."
for f in bronze/ibkr/*.py; do
  [ -f "$f" ] && python3 "$f" || true
done

# Live TWS position sync (ib_insync)
echo "→ IBKR TWS live sync..."
if [ -f "bronze/ibkr/ingest_ibkr_tws.py" ]; then
    python3 bronze/ibkr/ingest_ibkr_tws.py || echo "⚠️ IBKR TWS sync failed"
fi

# HKEX (Hong Kong equities)
echo "→ HKEX..."
for f in bronze/hkex/*.py; do
  [ -f "$f" ] && python3 "$f" || true
done

# Yahoo Finance (equities only - NO CRYPTO)
echo "→ Yahoo Finance (equities only)..."
for f in bronze/yfinance/*.py; do
  # Skip any crypto-related yfinance scripts
  if [[ "$f" != *"crypto"* ]]; then
    [ -f "$f" ] && python3 "$f" || true
  fi
done

# Manual uploads
echo "→ Manual uploads..."
for f in bronze/manual/*.py; do
  [ -f "$f" ] && python3 "$f" || true
done

echo "✅ Bronze complete"

# ─────────────────────────────────────────────
echo ""
echo "🔷 SILVER — Clean & Normalize"
echo "------------------------------------------"

# Crypto normalization (from Binance)
echo "→ Crypto (Binance source)..."
if [ -f "silver/crypto_normalize.py" ]; then
    python3 silver/crypto_normalize.py || echo "⚠️ Crypto silver failed"
fi

# Other silver scripts
for f in silver/*.py; do
  [ -f "$f" ] && python3 "$f" || true
done
echo "✅ Silver complete"

# ─────────────────────────────────────────────
echo ""
echo "🥇 GOLD — Curate by Asset Type"
echo "------------------------------------------"

# Crypto metrics (from Binance)
echo "→ Crypto metrics..."
if [ -f "gold/crypto/crypto_metrics.py" ]; then
    python3 gold/crypto/crypto_metrics.py || echo "⚠️ Crypto gold failed"
fi

# Other asset types
for asset in equity fx commodity market portfolio ipo; do
  if [ -d "gold/$asset" ]; then
    echo "→ $asset..."
    for f in gold/$asset/*.py; do
      [ -f "$f" ] && python3 "$f" || true
    done
  fi
done

# Portfolio positions: sync bronze → gold
echo "→ Portfolio positions (bronze→gold)..."
if [ -f "gold/portfolio/build_portfolio_snapshot.py" ]; then
    python3 gold/portfolio/build_portfolio_snapshot.py || echo "⚠️ Portfolio snapshot failed"
fi

echo "✅ Gold complete"

# ─────────────────────────────────────────────
echo ""
echo "📊 CONSUMPTION — Serve by Frontend Tab"
echo "------------------------------------------"
for tab in command lab performance portfolio market; do
  if [ -d "consumption/$tab" ]; then
    for f in consumption/$tab/*.py; do
      [ -f "$f" ] && python3 "$f" || true
    done
  fi
done
echo "✅ Consumption complete"

echo ""
echo "=========================================="
python3 "$WORKSPACE/agents/etl/sync_gold_layer_state.py" && echo "✅ gold_layer_state synced to DB"
echo "DAILY REFRESH COMPLETED: $(date)"
echo "Log: $LOG_FILE"
echo "=========================================="
