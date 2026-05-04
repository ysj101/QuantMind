"""小型株候補の発見と日次データ更新."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from quantmind.data.prices.ingest import update_codes
from quantmind.data.prices.yfinance_source import YFinanceSource
from quantmind.storage import get_conn

_TSE_SYMBOL_RE = re.compile(r"^(?P<code>\d{4})\.T$")


@dataclass(frozen=True)
class StockCandidate:
    code: str
    name: str
    market: str
    market_cap_jpy: int | None
    price_jpy: float | None = None


@dataclass(frozen=True)
class MarketDataBootstrapResult:
    candidates: list[StockCandidate] = field(default_factory=list)
    price_rows_by_code: dict[str, int] = field(default_factory=dict)


def _candidate_from_quote(quote: dict) -> StockCandidate | None:
    match = _TSE_SYMBOL_RE.match(str(quote.get("symbol") or ""))
    if not match:
        return None
    market_cap = quote.get("marketCap")
    price = quote.get("regularMarketPrice") or quote.get("regularMarketPreviousClose")
    return StockCandidate(
        code=match.group("code"),
        name=str(quote.get("shortName") or quote.get("longName") or match.group("code")),
        market=str(quote.get("exchange") or quote.get("fullExchangeName") or "JPX").lower(),
        market_cap_jpy=None if market_cap is None else int(market_cap),
        price_jpy=None if price is None else float(price),
    )


def discover_small_caps(
    *,
    limit: int = 50,
    max_market_cap_jpy: int = 50_000_000_000,
    max_price_jpy: float = 670.0,
) -> list[StockCandidate]:
    """Yahoo Finance スクリーナーで日本小型株候補を取得する."""
    import yfinance as yf
    from yfinance import EquityQuery

    query = EquityQuery(
        "and",
        [
            EquityQuery("eq", ["region", "jp"]),
            EquityQuery("lt", ["intradaymarketcap", max_market_cap_jpy]),
            EquityQuery("gt", ["intradayprice", 0]),
            EquityQuery("lt", ["intradayprice", max_price_jpy]),
        ],
    )
    response = yf.screen(query, size=limit, sortField="dayvolume", sortAsc=False)
    quotes = response.get("quotes", []) if isinstance(response, dict) else []

    out: list[StockCandidate] = []
    seen: set[str] = set()
    for quote in quotes:
        candidate = _candidate_from_quote(quote)
        if candidate is None or candidate.code in seen:
            continue
        if candidate.market_cap_jpy is not None and candidate.market_cap_jpy > max_market_cap_jpy:
            continue
        if candidate.price_jpy is not None and candidate.price_jpy > max_price_jpy:
            continue
        seen.add(candidate.code)
        out.append(candidate)
    return out


def upsert_stocks_master(candidates: list[StockCandidate]) -> int:
    """発見した候補を stocks_master に反映する."""
    if not candidates:
        return 0
    with get_conn() as conn:
        for c in candidates:
            conn.execute(
                "INSERT INTO stocks_master(code, name, market, market_cap_jpy) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(code) DO UPDATE SET "
                "name=excluded.name, market=excluded.market, "
                "market_cap_jpy=excluded.market_cap_jpy, snapshot_at=now()",
                [c.code, c.name, c.market, c.market_cap_jpy],
            )
    return len(candidates)


def bootstrap_market_data(
    as_of: date,
    *,
    limit: int = 50,
    lookback_days: int = 45,
    max_market_cap_jpy: int = 50_000_000_000,
    max_price_jpy: float = 670.0,
    candidates: list[StockCandidate] | None = None,
    price_source: YFinanceSource | None = None,
) -> MarketDataBootstrapResult:
    """小型株候補を発見し、株価データを更新する."""
    discovered = (
        candidates
        if candidates is not None
        else discover_small_caps(
            limit=limit,
            max_market_cap_jpy=max_market_cap_jpy,
            max_price_jpy=max_price_jpy,
        )
    )
    upsert_stocks_master(discovered)
    codes = [c.code for c in discovered]
    if not codes:
        return MarketDataBootstrapResult(candidates=discovered, price_rows_by_code={})

    source = price_source or YFinanceSource()
    start = as_of - timedelta(days=lookback_days)
    end = as_of + timedelta(days=1)
    return MarketDataBootstrapResult(
        candidates=discovered,
        price_rows_by_code=update_codes(source, codes, start, end),
    )
