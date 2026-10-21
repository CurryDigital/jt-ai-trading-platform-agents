#!/usr/bin/env python3
"""
ThetaData v3 REST client (via local Theta Terminal).

- Base URL from env THETA_TERMINAL_URL (default http://127.0.0.1:25503).
- The API key is NEVER handled here: the Terminal holds it (env THETADATA_API_KEY
  at Terminal launch). This client only talks to localhost.
- Raises TierGated on HTTP 403 with the vendor's tier message parsed out.
- Serial requests with a configurable inter-request delay (rate-limit respect).
"""
import json
import os
import re
import time
import urllib.request
import urllib.error
import urllib.parse

BASE = os.environ.get('THETA_TERMINAL_URL', 'http://127.0.0.1:25503')


class TierGated(RuntimeError):
    def __init__(self, endpoint: str, message: str):
        self.endpoint = endpoint
        m = re.search(r'requiring an? (\w+ )?(\w+) subscription', message, re.I)
        self.min_tier = (m.group(2).upper() if m else 'UNKNOWN')
        super().__init__(f'TIER_GATED[{self.min_tier}] {endpoint}: {message.strip()[:160]}')


class MarketClosed(RuntimeError):
    """HTTP 472 with the vendor's 'market was closed' body: a holiday inside a
    weekday range. NOT transient — callers must skip the day, not retry."""


class ThetaClient:
    def __init__(self, base: str = BASE, delay_s: float = 0.35, timeout_s: int = 120,
                 max_retries: int = 4):
        self.base = base.rstrip('/')
        self.delay_s = delay_s
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.requests_made = 0

    def get(self, path: str, params: dict) -> dict:
        """GET path with params; returns parsed JSON. Raises TierGated on 403."""
        url = f'{self.base}{path}?{urllib.parse.urlencode(params)}'
        last_err = None
        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(url, headers={'Accept': 'application/json'})
                with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                    self.requests_made += 1
                    time.sleep(self.delay_s)
                    body = r.read().decode('utf-8', 'replace')
                    return json.loads(body)
            except urllib.error.HTTPError as e:
                body = e.read().decode('utf-8', 'replace')
                if e.code == 403:
                    raise TierGated(path, body)
                if e.code == 472 and 'market was closed' in body:
                    raise MarketClosed(f'{path}: {body[:200]}')
                if e.code == 472 or e.code >= 500:  # transient vendor/terminal errors
                    last_err = f'HTTP {e.code}: {body[:200]}'
                    time.sleep(self.delay_s * (2 ** attempt) * 4)
                    continue
                raise RuntimeError(f'HTTP {e.code} on {path}: {body[:300]}')
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last_err = str(e)
                time.sleep(self.delay_s * (2 ** attempt) * 4)
        raise RuntimeError(f'{path} failed after {self.max_retries} attempts: {last_err}')

    # ---- endpoint helpers -------------------------------------------------
    def option_eod(self, symbol: str, trade_date: str, expiration: str = '*') -> list:
        """All contracts' EOD rows for one day. trade_date YYYY-MM-DD."""
        r = self.get('/v3/option/history/eod', {
            'symbol': symbol, 'expiration': expiration,
            'start_date': trade_date, 'end_date': trade_date, 'format': 'json'})
        return r.get('response', [])

    def option_greeks_eod(self, symbol: str, trade_date: str, expiration: str = '*',
                          rate_type: str = 'SOFR', annual_dividend: float | None = None) -> list:
        params: dict = {'symbol': symbol, 'expiration': expiration,
                        'start_date': trade_date, 'end_date': trade_date,
                        'rate_type': rate_type, 'format': 'json'}
        if annual_dividend is not None:
            params['annual_dividend'] = annual_dividend
        r = self.get('/v3/option/history/greeks/eod', params)
        return r.get('response', [])

    def option_open_interest(self, symbol: str, report_date: str, expiration: str = '*') -> list:
        r = self.get('/v3/option/history/open_interest', {
            'symbol': symbol, 'expiration': expiration, 'date': report_date, 'format': 'json'})
        return r.get('response', [])

    def stock_eod(self, symbol: str, trade_date: str) -> list:
        r = self.get('/v3/stock/history/eod', {
            'symbol': symbol, 'start_date': trade_date, 'end_date': trade_date,
            'format': 'json'})
        return r.get('response', [])

    def list_expirations(self, symbol: str) -> list:
        r = self.get('/v3/option/list/expirations', {'symbol': symbol, 'format': 'json'})
        return [x['expiration'] for x in r.get('response', [])]

    def list_strikes(self, symbol: str, expiration: str) -> list:
        r = self.get('/v3/option/list/strikes',
                     {'symbol': symbol, 'expiration': expiration, 'format': 'json'})
        return [x['strike'] for x in r.get('response', [])]
