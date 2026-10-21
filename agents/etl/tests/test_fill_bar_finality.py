"""t_823e0bbf — fill-bar finality gate for settle_pending_orders.

Regression: 2026-09-18 09:15 UTC cycle filled GLD OPEN orders at 402.45 from
a provisional premarket bar; post-close refresh revised the official bar to
open=400.48. The gate must leave orders resting while the fill bar's market
session is still open, and fill once it has closed.
"""
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..',
                                'gold', 'strategy'))

from rebuild_paper_positions import bar_is_final  # noqa: E402

D = date(2026, 9, 18)  # the GLD incident bar (a Friday)


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_us_premarket_bar_is_provisional():
    # 09:15 UTC = 05:15 ET — the exact incident moment.
    assert bar_is_final(D, 'US', ticker='GLD', now_utc=at(2026, 9, 18, 9, 15)) is False


def test_us_during_session_is_provisional():
    assert bar_is_final(D, 'US', ticker='GLD', now_utc=at(2026, 9, 18, 15, 0)) is False


def test_us_post_close_is_final():
    # 22:31 UTC post-close refresh = 18:31 ET.
    assert bar_is_final(D, 'US', ticker='GLD', now_utc=at(2026, 9, 18, 22, 31)) is True


def test_us_bar_final_next_morning():
    # Monday 09:15 UTC cycle fills Friday's bar (weekend gap).
    assert bar_is_final(D, 'US', ticker='GLD', now_utc=at(2026, 9, 21, 9, 15)) is True


def test_hk_bar_final_at_signal_cycle_time():
    # 09:15 UTC = 17:15 HKT — HK session (close 16:00) already done.
    assert bar_is_final(D, 'HK', now_utc=at(2026, 9, 18, 9, 15)) is True


def test_hk_bar_provisional_midday():
    # 07:00 UTC = 15:00 HKT — session still open.
    assert bar_is_final(D, 'HK', now_utc=at(2026, 9, 18, 7, 0)) is False


def test_cn_bar_final_at_signal_cycle_time():
    # 09:15 UTC = 17:15 CST — CN session (close 15:00) done.
    assert bar_is_final(D, 'CN', now_utc=at(2026, 9, 18, 9, 15)) is True


def test_global_crypto_today_provisional():
    assert bar_is_final(D, 'GLOBAL', ticker='BTC-USD',
                        now_utc=at(2026, 9, 18, 9, 15)) is False


def test_global_final_after_utc_midnight():
    assert bar_is_final(D, 'GLOBAL', ticker='BTC-USD',
                        now_utc=at(2026, 9, 19, 0, 1)) is True


def test_unknown_market_conservative():
    assert bar_is_final(D, None, now_utc=at(2026, 9, 18, 23, 59)) is False
    assert bar_is_final(D, None, now_utc=at(2026, 9, 19, 0, 0)) is True


def test_hsi_index_uses_hk_close():
    assert bar_is_final(D, 'INDEX', ticker='^HSI',
                        now_utc=at(2026, 9, 18, 9, 15)) is True
    assert bar_is_final(D, 'INDEX', ticker='^GSPC',
                        now_utc=at(2026, 9, 18, 9, 15)) is False


def test_dst_summer_us_close():
    # EDT (UTC-4): 16:00 ET close = 20:00 UTC.
    assert bar_is_final(D, 'US', now_utc=at(2026, 9, 18, 19, 59)) is False
    assert bar_is_final(D, 'US', now_utc=at(2026, 9, 18, 20, 0)) is True


def test_dst_winter_us_close():
    # EST (UTC-5): 16:00 ET close = 21:00 UTC.
    jan = date(2026, 1, 15)
    assert bar_is_final(jan, 'US', now_utc=at(2026, 1, 15, 20, 59)) is False
    assert bar_is_final(jan, 'US', now_utc=at(2026, 1, 15, 21, 0)) is True


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
