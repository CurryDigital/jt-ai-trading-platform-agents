# HK IPO Oversubscription Conventions — etnet vs HKEXnews

(kanban t_70bd6830, 2026-09-29; offsets verified live against DB)

Two silver columns report retail oversubscription for HK IPOs with
DIFFERENT conventions. They are NOT interchangeable.

| Column | Source | Convention |
|---|---|---|
| `silver.unified_ipo_calendar.oversubscription_retail` | etnet 'Latest IPO' pre-listing table (Subscription Rate) | Coverage vs initial retail pool |
| `silver.hk_ipo_allotment.oversub_retail_ann` | HKEXnews allotment results announcement | Oversubscription vs initial pool (includes the base 1x allocation) |

## Observed offset (2026-09-28 allotment cohort, verified 2026-09-29)

| Ticker | etnet (calendar) | HKEXnews (allotment) | Additive diff |
|---|---|---|---|
| 3228.HK | 93.30 | 94.25 | +0.95 |
| 3757.HK | 7.70 | 8.65 | +0.95 |
| 6731.HK | 207.60 | 208.56 | +0.96 |
| 9607.HK | 2.40 | 3.39 | +0.99 |

The offset is a consistent **+~1x additive** term (HKEXnews = etnet + ~1).
Note the RELATIVE difference is large for low-multiple IPOs: on 9607.HK,
3.39 vs 2.40 is a 41% relative difference. Never blend or compare the two
columns across sources without converting conventions first.

## Rules for downstream consumers

1. Pre-listing (before listing day): only
   `unified_ipo_calendar.oversubscription_retail` exists — the HKEXnews
   announcement lands on allotment evening but the allotment scrape runs
   post-listing.
2. Post-listing: `hk_ipo_allotment.oversub_retail_ann` is the official
   (HKEXnews-derived) authority.
3. Cross-source comparisons must subtract ~1x from the HKEXnews figure
   (or add ~1x to the etnet figure) before asserting agreement.
4. Do NOT treat a mismatch of ~+1x between the two columns as a data
   quality defect — it is the expected convention difference.

## Related timing notes

etnet pre-listing Subscription Rate publication time VARIES by allotment
day. The 2026-09-29 cohort (06802 CAMSENSE) was still unpublished at
15:20 UTC / 23:20 HKT (126-sample QA poll, kanban t_70bd6830), disproving
an earlier ~11:00-15:00 UTC assumption. The evening-fill cron
(`qr_etl.ipo_evening_results_fill`, 6d90e1655b3d) fires 16:30 + 18:30 UTC
Mon-Fri (cron '30 16,18 * * 1-5'; corrected 2026-09-29 per t_0a9dca93 —
previously documented as 18:00 UTC, which the expression never produced)
to hedge late publishers; the post-listing AAStocks listed scrape
(`refresh_ipo_calendar_daily.py` in Pipeline A, 08:30 UTC) is the
backstop authority for any cohort the evening fill misses.
