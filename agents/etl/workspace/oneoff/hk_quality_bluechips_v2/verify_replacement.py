import os
import psycopg2
from urllib.parse import urlparse

CSV_PATH = '/home/ubuntu/.hermes/kanban/boards/trading/attachments/t_2777be67/paper_trades_synthetic_replacement_B.csv'

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

with get_conn() as conn:
    with conn.cursor() as cur:
        # Basic counts
        cur.execute("SELECT count(*), count(DISTINCT ticker), status FROM gold.paper_trades_synthetic WHERE strategy_id = 'HK_Quality_BlueChips' GROUP BY status")
        rows = cur.fetchall()
        print("Rows/distinct_tickers by status:", rows)

        # Date ranges
        cur.execute("""
            SELECT min(entry_date), max(entry_date), min(exit_date), max(exit_date)
            FROM gold.paper_trades_synthetic WHERE strategy_id = 'HK_Quality_BlueChips'
        """)
        print("Date ranges:", cur.fetchone())

        # Same-day entry/exit (wash trade indicator)
        cur.execute("""
            SELECT count(*) FROM gold.paper_trades_synthetic
            WHERE strategy_id = 'HK_Quality_BlueChips' AND entry_date = exit_date
        """)
        print("Same-day entry/exit rows:", cur.fetchone()[0])

        # Cash filter dates should have zero entries
        cash_dates = ['2026-04-01', '2026-05-04', '2026-06-01', '2026-07-02']
        for d in cash_dates:
            cur.execute("""
                SELECT count(*) FROM gold.paper_trades_synthetic
                WHERE strategy_id = 'HK_Quality_BlueChips' AND entry_date = %s
            """, (d,))
            print(f"Entries on {d}:", cur.fetchone()[0])

        # Registry metrics
        cur.execute("""
            SELECT sharpe_oos, max_drawdown_oos, trade_count_oos, win_rate_oos, profit_factor_oos, returns_oos, last_signal_at
            FROM gold.strategy_registry WHERE strategy_id = 'HK_Quality_BlueChips'
        """)
        print("Registry OOS:", cur.fetchone())
