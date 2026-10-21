import os
import csv
import io
import psycopg2
from urllib.parse import urlparse

CSV_PATH = '/home/ubuntu/.hermes/kanban/boards/trading/attachments/t_2777be67/paper_trades_synthetic_replacement_B.csv'
IDEMPOTENCY_KEY = 'hk-quality-bluechips-replace-paper-synthetic-20260727-v4'

def get_conn():
    url = os.environ.get('OPENCLAW_DATABASE_URL')
    if url:
        p = urlparse(url)
        return psycopg2.connect(
            host=p.hostname,
            port=p.port or 5432,
            dbname=p.path.lstrip('/'),
            user=p.username,
            password=p.password,
            sslmode='require',
            options='-c search_path=gold,public'
        )
    return psycopg2.connect(
        host=os.environ.get('OPENCLAW_DB_HOST') or os.environ.get('AIRTRADING_DB_HOST'),
        port=os.environ.get('OPENCLAW_DB_PORT', '5432'),
        dbname='aitrading',
        user=os.environ.get('OPENCLAW_DB_USER') or os.environ.get('AIRTRADING_DB_USER'),
        password=os.environ.get('OPENCLAW_DB_PASSWORD') or os.environ.get('AIRTRADING_DB_PASSWORD') or os.environ.get('PGPASSWORD'),
        sslmode='require',
        options='-c search_path=gold,public'
    )

# Read CSV into memory, validate row count
rows = []
with open(CSV_PATH, 'r', newline='') as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

print(f"CSV data rows: {len(rows)}")
assert len(rows) == 230, f"Expected 230 rows, got {len(rows)}"
assert set(r['strategy_id'] for r in rows) == {'HK_Quality_BlueChips'}
assert set(r['status'] for r in rows) == {'closed'}
assert set(r['direction'] for r in rows) == {'LONG'}

with get_conn() as conn:
    with conn.cursor() as cur:
        # Pre-state
        cur.execute("SELECT count(*) FROM gold.paper_trades_synthetic WHERE strategy_id = 'HK_Quality_BlueChips'")
        old_cnt = cur.fetchone()[0]
        print(f"Pre-replacement row count: {old_cnt}")

        cur.execute("""
            SELECT sharpe_oos, max_drawdown_oos, trade_count_oos, win_rate_oos, profit_factor_oos, returns_oos
            FROM gold.strategy_registry WHERE strategy_id = 'HK_Quality_BlueChips'
        """)
        old_metrics = cur.fetchone()
        print(f"Pre-replacement OOS metrics: {old_metrics}")

        # Idempotency check: if state already matches, skip
        if old_cnt == 230 and old_metrics and \
           abs(float(old_metrics[0]) - 0.8594) < 1e-9 and \
           abs(float(old_metrics[1]) - (-0.2060)) < 1e-9 and \
           old_metrics[2] == 145:
            print("State already matches target; treating as idempotent.")
            raise SystemExit(0)

        # Delete old rows
        cur.execute("DELETE FROM gold.paper_trades_synthetic WHERE strategy_id = 'HK_Quality_BlueChips'")
        deleted = cur.rowcount
        print(f"Deleted rows: {deleted}")

        # COPY from stdin
        copy_sql = """
            COPY gold.paper_trades_synthetic (
                strategy_id, ticker, direction, entry_date, exit_date,
                entry_price, exit_price, n_shares, pnl, pnl_pct, status,
                signal_weight, assigned_capital
            ) FROM STDIN WITH (FORMAT csv, HEADER true)
        """
        with open(CSV_PATH, 'r', newline='') as f:
            cur.copy_expert(copy_sql, f)

        cur.execute("SELECT count(*) FROM gold.paper_trades_synthetic WHERE strategy_id = 'HK_Quality_BlueChips'")
        new_cnt = cur.fetchone()[0]
        print(f"Post-copy row count: {new_cnt}")
        assert new_cnt == 230, f"Expected 230 rows after copy, got {new_cnt}"

        # Update registry
        cur.execute("""
            UPDATE gold.strategy_registry
            SET
                sharpe_oos = 0.8594,
                max_drawdown_oos = -0.2060,
                trade_count_oos = 145,
                win_rate_oos = 0.7241,
                profit_factor_oos = 2.6979,
                returns_oos = 0.5309,
                last_signal_at = '2026-07-02 00:00:00'::timestamp,
                updated_at = now()
            WHERE strategy_id = 'HK_Quality_BlueChips'
        """)
        assert cur.rowcount == 1, f"Expected 1 registry row updated, got {cur.rowcount}"
        print("Updated strategy_registry OOS columns")

        conn.commit()
        print("Committed")

        # Post-verify
        cur.execute("SELECT count(*) FROM gold.paper_trades_synthetic WHERE strategy_id = 'HK_Quality_BlueChips'")
        final_cnt = cur.fetchone()[0]
        cur.execute("""
            SELECT sharpe_oos, max_drawdown_oos, trade_count_oos, win_rate_oos, profit_factor_oos, returns_oos
            FROM gold.strategy_registry WHERE strategy_id = 'HK_Quality_BlueChips'
        """)
        final_metrics = cur.fetchone()
        print(f"Final row count: {final_cnt}")
        print(f"Final OOS metrics: {final_metrics}")
