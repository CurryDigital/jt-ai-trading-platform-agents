#!/usr/bin/env python3
"""Production headline scorer for silver.historical_news enrichment.

Task t_f7f1c624 — approved methodology (scrum_master 2026-08-13):
  dual-lexicon VADER + Loughran-McDonald, language gate, calibrated label rule.

Calibration result (150 hand-labeled headlines, 98 English; see
calibration_report.md / calibration_scored_r2.csv):
  SHIPPED RULE `lexicon-finvader1-lm1`:
    lang != 'en'            -> sent_label = NULL (excluded from aggregates)
    fin_vader >=  0.2       -> bull
    fin_vader <= -0.2       -> bear
    else                    -> neutral
  macro-F1 = 0.609 on calibration labels (gate >= 0.60 PASS).
  LM score is computed and stored but NOT used in the label rule: adding it
  reduced macro-F1 on headlines (LM is 10-K-tuned). Keep for research use.

  fin_vader = stock VADER lexicon + FIN_LEXICON (curated finance market-move
  vocabulary; see FIN_LEXICON below). Stock VADER compound is also returned as
  vader_score for comparability with silver.news_items / gold.news_sentiment_daily
  (scorer='lexicon-vader1') — that aggregate pipeline is UNCHANGED.

Determinism: langdetect is seeded (DetectorFactory.seed=0).

Usage: from scorer import score_headline, label_from_scores
"""
import json
import os
import re

from langdetect import detect, LangDetectException, DetectorFactory
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

DetectorFactory.seed = 0  # deterministic language detection

_LABEL_THRESHOLD = 0.2
SCORER_ID = "lexicon-finvader1-lm1"

# Curated finance market-move extension for VADER (generic market vocabulary;
# developed and calibrated in calibrate_r2.py against 150 hand-labeled
# headlines — NOT refitted per-sample).
FIN_LEXICON = {
    # bullish direction / market moves
    "rise": 1.6, "rises": 1.6, "rose": 1.6, "rising": 1.6,
    "gain": 1.5, "gains": 1.5, "gained": 1.5, "gaining": 1.5,
    "rally": 1.8, "rallies": 1.8, "rallied": 1.8, "rallying": 1.8,
    "soar": 2.2, "soars": 2.2, "soared": 2.2, "soaring": 2.2,
    "surge": 2.0, "surges": 2.0, "surged": 2.0, "surging": 2.0,
    "jump": 1.7, "jumps": 1.7, "jumped": 1.7,
    "climb": 1.5, "climbs": 1.5, "climbed": 1.5,
    "advance": 1.3, "advances": 1.3, "advanced": 1.3,
    "rebound": 1.7, "rebounds": 1.7, "rebounded": 1.7,
    "bounce": 1.4, "bounces": 1.4, "bounced": 1.4,
    "higher": 1.2, "uptick": 1.4, "upswing": 1.6,
    "record-setting": 1.8, "skyrocket": 2.4, "skyrockets": 2.4,
    "outperform": 1.8, "outperforms": 1.8,
    "inflows": 1.4, "inflow": 1.4,
    "upgrade": 1.5, "upgrades": 1.5, "upgraded": 1.5,
    "beats": 1.6, "tops": 1.2, "exceeds": 1.4,
    "bullish": 2.0, "bull": 1.4, "boom": 1.8, "booms": 1.8,
    "steady": 0.8, "steadies": 0.8, "stabilizes": 0.9, "stabilize": 0.9,
    "recovers": 1.4, "recover": 1.4, "recovery": 1.3,
    "eases": 0.8, "extends": 0.5,
    # bearish direction / market moves
    "fall": -1.6, "falls": -1.6, "fell": -1.6, "falling": -1.6,
    "drop": -1.5, "drops": -1.5, "dropped": -1.5,
    "plunge": -2.2, "plunges": -2.2, "plunged": -2.2,
    "sink": -1.8, "sinks": -1.8, "sank": -1.8,
    "slip": -1.3, "slips": -1.3, "slipped": -1.3,
    "slump": -1.9, "slumps": -1.9, "slumped": -1.9,
    "tumble": -2.0, "tumbles": -2.0, "tumbled": -2.0,
    "decline": -1.5, "declines": -1.5, "declined": -1.5,
    "lower": -1.1, "downward": -1.3, "downturn": -1.8,
    "selloff": -2.0, "sell-off": -2.0, "sell": -0.7,
    "crash": -2.4, "crashes": -2.4, "crashed": -2.4,
    "crater": -2.2, "craters": -2.2, "rout": -2.1,
    "plummet": -2.3, "plummets": -2.3, "nosedive": -2.3,
    "collapse": -2.2, "collapses": -2.2, "collapsed": -2.2,
    "slide": -1.5, "slides": -1.5, "slid": -1.5,
    "retreat": -1.3, "retreats": -1.3,
    "outflows": -1.4, "outflow": -1.4,
    "downgrade": -1.6, "downgrades": -1.6, "downgraded": -1.6,
    "misses": -1.3, "underperform": -1.7,
    "bearish": -2.0, "bear": -1.3, "bears": -1.3,
    "warn": -1.2, "warns": -1.2, "warning": -1.3, "warnings": -1.3,
    "fear": -1.5, "fears": -1.5, "scare": -1.4, "scares": -1.4,
    "waver": -0.9, "wavers": -0.9, "volatile": -0.9, "volatility": -0.8,
    "weakens": -1.3, "weaken": -1.3, "weakening": -1.3,
    "erases": 0.9, "erase": 0.9,
    "losses": -1.8,  # VADER has 'loss' but weak; strengthen
    "down": -1.1, "up": 1.0,
    "stall": -1.3, "stalls": -1.3, "stalled": -1.3,
    "correction": -1.2, "corrections": -1.2,
    "dampen": -1.2, "dampens": -1.2, "dampened": -1.2,
    "drift": -0.6, "drifts": -0.6,
}

_stock_vader = SentimentIntensityAnalyzer()
_fin_vader = SentimentIntensityAnalyzer()
_fin_vader.lexicon.update(FIN_LEXICON)

# Loughran-McDonald 2018 sentiment word lists (canonical counts:
# negative=2355, positive=354), extracted from the master dictionary.
_LEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lm_lexicon.json")
with open(_LEX_PATH, encoding="utf-8") as _f:
    _LEX = json.load(_f)
_LM_NEG = frozenset(_LEX["negative"])
_LM_POS = frozenset(_LEX["positive"])

_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-zA-Z']+")


def normalize_headline(text: str) -> str:
    """Fix GDELT spacing artifacts: ' , ' -> ', ', ' $ 500M' -> '$500M' etc."""
    if not text:
        return ""
    t = _WS.sub(" ", text).strip()
    t = re.sub(r"\s+([,.!?;:%)])", r"\1", t)      # space before punctuation
    t = re.sub(r"([(])\s+", r"\1", t)             # space after open paren
    t = re.sub(r"\$\s+(\d)", r"$\1", t)           # '$ 500' -> '$500'
    t = re.sub(r"(\d)\s+%", r"\1%", t)            # '3 . 8 %' -> handled below
    t = re.sub(r"(\d)\s+\.\s+(\d)", r"\1.\2", t)  # '3 . 8' -> '3.8'
    return t


def detect_lang(text: str) -> str:
    try:
        return detect(text)
    except LangDetectException:
        return "unk"


def score_headline(headline: str) -> dict:
    """Score one headline. Returns raw scores; use label_from_scores for the
    calibrated label."""
    text = normalize_headline(headline or "")
    lang = detect_lang(text) if text else "unk"
    v_base = _stock_vader.polarity_scores(text)["compound"] if text else 0.0
    if lang == "en":
        v_fin = _fin_vader.polarity_scores(text)["compound"]
        toks = [t.lower() for t in _TOKEN.findall(text)]
        lm_pos = sum(1 for t in toks if t in _LM_POS)
        lm_neg = sum(1 for t in toks if t in _LM_NEG)
        lm_score = (lm_pos - lm_neg) / (lm_pos + lm_neg) if (lm_pos + lm_neg) else 0.0
    else:
        v_fin, lm_score, lm_pos, lm_neg = 0.0, 0.0, 0, 0
    return {
        "lang": lang,
        "vader_score": round(v_base, 4),   # stock VADER — news_items comparable
        "fin_vader_score": round(v_fin, 4),  # label driver
        "lm_score": round(lm_score, 4),
        "lm_pos": lm_pos,
        "lm_neg": lm_neg,
    }


def label_from_scores(scores: dict):
    """Calibrated shipped rule. Returns 'bull'/'bear'/'neutral'/None."""
    if scores["lang"] != "en":
        return None
    v = scores["fin_vader_score"]
    if v >= _LABEL_THRESHOLD:
        return "bull"
    if v <= -_LABEL_THRESHOLD:
        return "bear"
    return "neutral"


# Simple risk keyword hits (for impact heuristic; mirrors the spirit of
# news_items.risk_hits — qr_etl may substitute its own count when backfilling
# from news_items).
RISK_KEYWORDS = frozenset(
    "war wars invasion sanction sanctions tariff tariffs default defaults crisis "
    "crash recession inflation hike hikes cut cuts fed fomc ecb boj pboc sec doj "
    "lawsuit probe fraud bankruptcy default downgrade emergency bailout conflict "
    "missile nuclear strike strikes escalation".split()
)


def risk_hits(text: str) -> int:
    toks = [t.lower() for t in _TOKEN.findall(normalize_headline(text or ""))]
    return sum(1 for t in toks if t in RISK_KEYWORDS)


def impact_label(risk: int, dup_count: int) -> str:
    """Heuristic impact tier (no ground truth — documented heuristic):
    High: dup_count>=5 or risk>=2 | Medium: dup_count>=2 or risk>=1 | else Low."""
    if dup_count >= 5 or risk >= 2:
        return "High"
    if dup_count >= 2 or risk >= 1:
        return "Med"
    return "Low"


if __name__ == "__main__":
    tests = [
        "Bitcoin at record high ! Crypto token touches $124k , gaining nearly 32 % in 2025 Here why",
        "Dow Jones plunges 785 points on expanding Iran war fears",
        "Gold Rates in Pakistan Today - Per Tola Gold Price",
        "Биткоин сохраняет давление",
        "Walken Price Down 3 . 8 % This Week ( WLKN )",
        "Wall Street coasts to the finish of its latest record - setting week",
    ]
    for t in tests:
        s = score_headline(t)
        print(label_from_scores(s), s, "|", normalize_headline(t)[:60])
