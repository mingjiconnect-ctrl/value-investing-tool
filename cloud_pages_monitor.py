from __future__ import annotations

import argparse
import base64
import gzip
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path.cwd()
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "data" / "latest_rankings.json"
DIST = ROOT / "dist"
FUNDAMENTALS_SNAPSHOT = ROOT / "data" / "fundamentals_snapshot.json"
FUNDAMENTALS_SNAPSHOT_GZ = ROOT / "data" / "fundamentals_snapshot.json.gz"
FUNDAMENTALS_SNAPSHOT_B64 = ROOT / "data" / "fundamentals_snapshot.json.gz.b64"
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
SEC_UA = os.environ.get("SEC_USER_AGENT", "sp500-monitor/0.1 contact@example.com")
EXCLUDED_SECTORS = {"Financials", "Real Estate", "Utilities"}
_FUNDAMENTALS_SNAPSHOT_CACHE: dict[str, Any] | None = None


@dataclass(frozen=True)
class Company:
    ticker: str
    name: str
    sector: str
    industry: str
    cik: str | None


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.done = False
        self.in_row = False
        self.in_cell = False
        self.skip = 0
        self.row: list[str] = []
        self.cell: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k: v or "" for k, v in attrs}
        if tag == "table" and not self.in_table and not self.done and "wikitable" in attrs_d.get("class", ""):
            self.in_table = True
            return
        if not self.in_table:
            return
        if tag in {"script", "style", "sup"}:
            self.skip += 1
        elif tag == "tr":
            self.in_row = True
            self.row = []
        elif tag in {"td", "th"} and self.in_row:
            self.in_cell = True
            self.cell = []

    def handle_endtag(self, tag: str) -> None:
        if not self.in_table:
            return
        if tag in {"script", "style", "sup"} and self.skip:
            self.skip -= 1
        elif tag in {"td", "th"} and self.in_cell:
            self.row.append(clean(" ".join(self.cell)))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.row:
                self.rows.append(self.row)
            self.in_row = False
        elif tag == "table":
            self.in_table = False
            self.done = True

    def handle_data(self, data: str) -> None:
        if self.in_table and self.in_cell and not self.skip:
            self.cell.append(data)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\[[^\]]+\]", "", text).replace("\xa0", " ")).strip()


def get(url: str, headers: dict[str, str], timeout: int = 30, attempts: int = 3) -> bytes:
    last: Exception | None = None
    for n in range(attempts):
        try:
            with urlopen(Request(url, headers=headers), timeout=timeout) as r:
                data = r.read()
                if r.headers.get("Content-Encoding", "").lower() == "gzip":
                    return gzip.decompress(data)
                return data
        except Exception as exc:  # noqa: BLE001 - network retry boundary
            last = exc
            if n == attempts - 1:
                raise
            time.sleep(0.8 * (n + 1))
    raise RuntimeError(last)


def cache_json(name: str, url: str, hours: float, headers: dict[str, str]) -> Any:
    path = CACHE / name
    if path.exists() and datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < timedelta(hours=hours):
        return json.loads(path.read_text())
    payload = json.loads(get(url, headers).decode("utf-8", "replace"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def sp500() -> list[Company]:
    path = CACHE / "sp500.html"
    if path.exists() and datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < timedelta(hours=12):
        html = path.read_text(encoding="utf-8")
    else:
        html = get(WIKI_URL, {"User-Agent": "Mozilla/5.0"}).decode("utf-8", "replace")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    p = TableParser()
    p.feed(html)
    headers = {v: i for i, v in enumerate(p.rows[0])}
    out: list[Company] = []
    for row in p.rows[1:]:
        if len(row) < len(headers):
            continue
        cik = row[headers["CIK"]] if "CIK" in headers else None
        out.append(
            Company(
                ticker=row[headers["Symbol"]].replace(".", "-").upper(),
                name=row[headers["Security"]],
                sector=row[headers["GICS Sector"]],
                industry=row[headers["GICS Sub-Industry"]],
                cik=str(cik).zfill(10) if cik else None,
            )
        )
    return out


FLOW = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "Depreciation"],
    "rd": ["ResearchAndDevelopmentExpense"],
}
INST = {
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "debt": ["LongTermDebtAndFinanceLeaseObligationsCurrent", "LongTermDebtCurrent", "ShortTermBorrowings"],
    "long_debt": ["LongTermDebtAndFinanceLeaseObligationsNoncurrent", "LongTermDebtNoncurrent"],
}


def candidates(facts: dict[str, Any], tags: list[str], unit: str = "USD") -> list[dict[str, Any]]:
    ans = []
    preferred = ["shares"] if unit == "shares" else ["USD", "USD/shares", "pure"]
    for tag in tags:
        metric = facts.get(tag, {})
        units = metric.get("units", {})
        keys = [x for x in preferred if x in units] + [x for x in units if x not in preferred]
        for key in keys:
            for item in units.get(key, []):
                if item.get("val") is not None and item.get("form") in {None, "10-K", "10-Q", "20-F", "40-F"}:
                    ans.append(item)
    return ans


def val(item: dict[str, Any] | None) -> float | None:
    try:
        return None if item is None else float(item["val"])
    except (KeyError, TypeError, ValueError):
        return None


def annual(item: dict[str, Any]) -> bool:
    if item.get("fp") == "FY":
        return True
    try:
        return (date.fromisoformat(item["end"]) - date.fromisoformat(item["start"])).days >= 300
    except Exception:
        return False


def latest(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return max(items, key=lambda x: (str(x.get("filed", "")), str(x.get("end", "")), str(x.get("accn", "")))) if items else None


def annual_fact(facts: dict[str, Any], tags: list[str], unit: str = "USD") -> dict[str, Any] | None:
    return latest([x for x in candidates(facts, tags, unit) if annual(x)])


def instant_fact(facts: dict[str, Any], tags: list[str], unit: str = "USD") -> dict[str, Any] | None:
    return latest([x for x in candidates(facts, tags, unit) if x.get("end") and not x.get("start")] or [x for x in candidates(facts, tags, unit) if x.get("end")])


def cagr(history: list[dict[str, Any]], periods: int = 3) -> float | None:
    clean_hist = [x for x in history if x.get("value") and x["value"] > 0]
    if len(clean_hist) < 2:
        return None
    clean_hist = clean_hist[-(periods + 1) :]
    years = max(1, clean_hist[-1]["fy"] - clean_hist[0]["fy"])
    return (clean_hist[-1]["value"] / clean_hist[0]["value"]) ** (1 / years) - 1


def facts(cik: str) -> dict[str, Any]:
    return cache_json(
        f"companyfacts_{cik}.json",
        FACTS_URL.format(cik=cik),
        12,
        {"User-Agent": SEC_UA, "Accept": "application/json", "Accept-Encoding": "gzip"},
    )


def fundamentals_snapshot() -> dict[str, Any]:
    global _FUNDAMENTALS_SNAPSHOT_CACHE
    if _FUNDAMENTALS_SNAPSHOT_CACHE is None:
        if FUNDAMENTALS_SNAPSHOT.exists():
            _FUNDAMENTALS_SNAPSHOT_CACHE = json.loads(FUNDAMENTALS_SNAPSHOT.read_text(encoding="utf-8"))
        elif FUNDAMENTALS_SNAPSHOT_GZ.exists():
            _FUNDAMENTALS_SNAPSHOT_CACHE = json.loads(gzip.decompress(FUNDAMENTALS_SNAPSHOT_GZ.read_bytes()).decode("utf-8"))
        elif FUNDAMENTALS_SNAPSHOT_B64.exists():
            raw = base64.b64decode(FUNDAMENTALS_SNAPSHOT_B64.read_text(encoding="utf-8"))
            _FUNDAMENTALS_SNAPSHOT_CACHE = json.loads(gzip.decompress(raw).decode("utf-8"))
        else:
            _FUNDAMENTALS_SNAPSHOT_CACHE = {"fundamentals": {}}
    return _FUNDAMENTALS_SNAPSHOT_CACHE


def snapshot_fundamentals(cik: str) -> dict[str, Any] | None:
    record = fundamentals_snapshot().get("fundamentals", {}).get(cik)
    return dict(record) if isinstance(record, dict) else None


def fundamentals(raw: dict[str, Any]) -> dict[str, Any]:
    us = raw.get("facts", {}).get("us-gaap", {})
    dei = raw.get("facts", {}).get("dei", {})
    f = {k: val(annual_fact(us, tags)) for k, tags in FLOW.items()}
    i = {k: val(instant_fact(us, tags)) for k, tags in INST.items()}
    debt = sum(x for x in [i.get("debt"), i.get("long_debt")] if x is not None) or None
    revenue_history = []
    by_year: dict[int, dict[str, Any]] = {}
    for item in [x for x in candidates(us, FLOW["revenue"]) if annual(x)]:
        if item.get("fy") is not None:
            y = int(item["fy"])
            if y not in by_year or latest([item, by_year[y]]) is item:
                by_year[y] = item
    for y in sorted(by_year):
        revenue_history.append({"fy": y, "value": val(by_year[y])})
    cfo, capex, ni, da = f.get("cfo"), f.get("capex"), f.get("net_income"), f.get("da")
    owner_earnings = cfo - abs(capex) if cfo is not None and capex is not None else (ni + da if ni is not None and da is not None else None)
    return {
        **f,
        **i,
        "debt": debt,
        "revenue_history": revenue_history,
        "revenue_cagr_3y": cagr(revenue_history),
        "shares_outstanding": val(instant_fact(dei, ["EntityCommonStockSharesOutstanding"], "shares")),
        "diluted_shares": val(annual_fact(us, ["WeightedAverageNumberOfDilutedSharesOutstanding"], "shares")),
        "owner_earnings": owner_earnings,
    }


def price(ticker: str) -> dict[str, Any]:
    p = cache_json(f"price_{ticker}.json", YAHOO_URL.format(ticker=quote(ticker)), 0.25, {"User-Agent": "Mozilla/5.0"})
    result = (p.get("chart", {}).get("result") or [{}])[0]
    meta = result.get("meta", {})
    px = meta.get("regularMarketPrice")
    ts = meta.get("regularMarketTime")
    if px is None:
        closes = ((result.get("indicators", {}).get("quote") or [{}])[0].get("close") or [])
        px = next((x for x in reversed(closes) if x is not None), None)
    if px is None:
        raise RuntimeError("missing_price")
    return {"price": float(px), "currency": meta.get("currency"), "market_time": datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None}


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def div(a: float | None, b: float | None) -> float | None:
    return None if a is None or b in {None, 0} else a / b


def rscore(v: float | None, lo: float, hi: float) -> float | None:
    return None if v is None or hi == lo else clamp((v - lo) / (hi - lo), 0, 1) * 100


def inv(v: float | None, good: float, bad: float) -> float | None:
    return None if v is None or bad == good else clamp((bad - v) / (bad - good), 0, 1) * 100


def avg(*xs: float | None) -> float | None:
    ys = [x for x in xs if x is not None]
    return sum(ys) / len(ys) if ys else None


def weighted(*xs: tuple[float | None, float]) -> float | None:
    ys = [(x, w) for x, w in xs if x is not None]
    return sum(x * w for x, w in ys) / sum(w for _, w in ys) if ys else None


def shares(diluted: float | None, outstanding: float | None) -> tuple[float | None, str | None]:
    if diluted is not None and diluted >= 1_000_000:
        return diluted, None
    if outstanding is not None and outstanding >= 1_000_000:
        return outstanding, "using_current_shares_outstanding_fallback"
    if diluted is not None or outstanding is not None:
        return None, "invalid_or_implausible_share_count"
    return None, "missing_share_count"


def dcf(owner_earnings: float, cash: float, debt: float, growth: float, discount: float, terminal: float) -> float | None:
    if owner_earnings <= 0 or discount <= terminal:
        return None
    cf = owner_earnings
    pv = 0.0
    for year in range(1, 11):
        g = growth + (terminal - growth) * ((year - 1) / 9)
        cf *= 1 + g
        pv += cf / ((1 + discount) ** year)
    tv = cf * (1 + terminal) / (discount - terminal)
    return max(0.0, pv + tv / ((1 + discount) ** 10) + cash - debt)


def score(company: Company, f: dict[str, Any] | None, q: dict[str, Any] | None, err: str | None) -> dict[str, Any]:
    notes = [err] if err else []
    risks = []
    sh, share_note = shares(f.get("diluted_shares") if f else None, f.get("shares_outstanding") if f else None)
    if share_note:
        notes.append(share_note)
    px = q.get("price") if q else None
    supported = company.sector not in EXCLUDED_SECTORS
    revenue, oe, ni = (f or {}).get("revenue"), (f or {}).get("owner_earnings"), (f or {}).get("net_income")
    op, gp, assets, liabilities, equity = (f or {}).get("operating_income"), (f or {}).get("gross_profit"), (f or {}).get("assets"), (f or {}).get("liabilities"), (f or {}).get("equity")
    cash, debt, rd = (f or {}).get("cash") or 0.0, (f or {}).get("debt") or 0.0, (f or {}).get("rd")
    rev_cagr = (f or {}).get("revenue_cagr_3y")
    fair, gap, scenarios = None, None, {}
    if supported and px and sh and oe and oe > 0:
        g = clamp(rev_cagr if rev_cagr is not None else 0.03, -0.05, 0.15)
        setup = {"base": (g, 0.09, 0.025, 0.55), "bull": (clamp(g + 0.03, -0.02, 0.18), 0.08, 0.03, 0.20), "black_swan": (clamp(g - 0.07, -0.10, 0.08), 0.11, 0.0, 0.25)}
        fair = 0.0
        for name, (growth, discount, terminal, weight) in setup.items():
            ev = dcf(oe, cash, debt, growth, discount, terminal)
            per_share = ev / sh if ev and sh else None
            scenarios[name] = {"growth": growth, "discount_rate": discount, "terminal_growth": terminal, "weight": weight, "per_share": per_share}
            if per_share is not None:
                fair += per_share * weight
        fair = fair or None
        gap = fair / px - 1 if fair and px else None
    else:
        risks.append("insufficient_valuation_data")
        if not supported:
            notes.append("generic_owner_earnings_dcf_not_supported_for_sector")
            risks.append("sector_model_limit")
    market_cap = px * sh if px and sh else None
    fcf_margin, op_margin, gross_margin = div(oe, revenue), div(op, revenue), div(gp, revenue)
    roe, debt_assets = div(ni, equity), div(liabilities, assets)
    oe_yield, rd_sales = div(oe, market_cap), div(rd, revenue)
    discount_score = rscore(gap, -0.20, 0.80)
    data_items = [px, sh, revenue, oe, ni, op, assets, liabilities, equity, cash, debt, rev_cagr]
    data_score = 100 * sum(x is not None for x in data_items) / len(data_items)
    buffett = avg(rscore(oe_yield, 0.02, 0.10), rscore(fcf_margin, 0.03, 0.18), rscore(roe, 0.08, 0.25), inv(debt_assets, 0.30, 0.80), rscore(op_margin, 0.08, 0.28))
    moat = avg(rscore(gross_margin, 0.25, 0.65), rscore(op_margin, 0.10, 0.32), rscore(roe, 0.10, 0.30), rscore(fcf_margin, 0.05, 0.20), inv(abs(rev_cagr) if rev_cagr is not None else None, 0, 0.30))
    peg = None if not market_cap or not ni or ni <= 0 or not rev_cagr or rev_cagr <= 0 else market_cap / ni / (rev_cagr * 100)
    peg_score = None if peg is None or peg <= 0 else (100.0 if peg <= 1 else (0.0 if peg >= 3 else (3 - peg) / 2 * 100))
    lynch = avg(rscore(rev_cagr, 0.02, 0.18), peg_score, rscore(fcf_margin, 0.02, 0.15), rscore(op_margin, 0.05, 0.25))
    fisher = avg(rscore(rev_cagr, 0.04, 0.20), rscore(gross_margin, 0.30, 0.70), rscore(op_margin, 0.08, 0.30), rscore(rd_sales, 0.03, 0.18), rscore(fcf_margin, 0.03, 0.18))
    growth_style = supported and (rev_cagr or 0) >= 0.06 and (lynch or 0) >= 45 and (fisher or 0) >= 45 and (fcf_margin or -1) > 0 and (op_margin or -1) > 0 and data_score >= 75
    value_score = weighted((discount_score, 0.35), (buffett, 0.35), (moat, 0.20), (data_score, 0.10)) if supported and not growth_style and gap is not None and gap >= 0 and (buffett or 0) >= 45 and (moat or 0) >= 40 and (oe_yield or 0) >= 0.035 and data_score >= 75 else None
    growth_score = weighted((discount_score, 0.25), (lynch, 0.40), (fisher, 0.30), (data_score, 0.05)) if growth_style and gap is not None and gap >= -0.15 and discount_score is not None else None
    def rnd(x: float | None, n: int = 4) -> float | None:
        return None if x is None or not math.isfinite(x) else round(x, n)
    if gap is not None and gap < 0:
        risks.append("priced_above_weighted_fair_value")
    return {
        "ticker": company.ticker,
        "name": company.name,
        "cik": company.cik,
        "issuer_key": company.cik or company.name.lower(),
        "sector": company.sector,
        "industry": company.industry,
        "price": rnd(px),
        "currency": q.get("currency") if q else None,
        "market_time": q.get("market_time") if q else None,
        "fair_value": rnd(fair),
        "fair_value_gap": rnd(gap, 6),
        "value_rank_score": rnd(value_score),
        "growth_rank_score": rnd(growth_score),
        "buffett_score": rnd(buffett),
        "moat_score": rnd(moat),
        "lynch_score": rnd(lynch),
        "fisher_score": rnd(fisher),
        "discount_score": rnd(discount_score),
        "data_score": round(data_score, 4),
        "revenue_cagr_3y": rnd(rev_cagr, 6),
        "owner_earnings_yield": rnd(oe_yield, 6),
        "fcf_margin": rnd(fcf_margin, 6),
        "operating_margin": rnd(op_margin, 6),
        "gross_margin": rnd(gross_margin, 6),
        "roe": rnd(roe, 6),
        "debt_to_assets": rnd(debt_assets, 6),
        "scenarios": scenarios,
        "source_notes": notes,
        "risk_tags": sorted(set(risks)),
        "status": "rankable" if value_score is not None or growth_score is not None else "insufficient_data",
    }


def dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for row in rows:
        key = row.get("issuer_key") or row["ticker"]
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def run(limit: int, pause: float) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    rows, errors = [], []
    universe = sp500()
    if limit:
        universe = universe[:limit]
    for n, c in enumerate(universe, 1):
        print(f"[{n}/{len(universe)}] {c.ticker} {c.name}", flush=True)
        f, q, err = None, None, None
        try:
            if not c.cik:
                raise RuntimeError("missing_cik")
            f = fundamentals(facts(c.cik))
            time.sleep(pause)
        except Exception as exc:  # noqa: BLE001
            fallback = snapshot_fundamentals(c.cik) if c.cik else None
            if fallback:
                f = fallback
                err = f"fundamentals_snapshot_fallback:live_sec_{type(exc).__name__}:{exc}"
                errors.append({"ticker": c.ticker, "stage": "fundamentals_live", "error": str(exc), "fallback": "fundamentals_snapshot"})
            else:
                err = f"fundamentals_error:{type(exc).__name__}:{exc}"
                errors.append({"ticker": c.ticker, "stage": "fundamentals", "error": str(exc)})
        try:
            q = price(c.ticker)
            time.sleep(max(0.03, pause / 2))
        except Exception as exc:  # noqa: BLE001
            perr = f"price_error:{type(exc).__name__}:{exc}"
            err = f"{err};{perr}" if err else perr
            errors.append({"ticker": c.ticker, "stage": "price", "error": str(exc)})
        rows.append(score(c, f, q, err))
    values = dedupe(sorted([r for r in rows if r["value_rank_score"] is not None], key=lambda x: x["value_rank_score"], reverse=True))
    growth = dedupe(sorted([r for r in rows if r["growth_rank_score"] is not None], key=lambda x: x["growth_rank_score"], reverse=True))
    payload = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "started_at": started.isoformat(),
            "universe": "S&P 500",
            "processed_companies": len(rows),
            "rankable_companies": sum(r["status"] == "rankable" for r in rows),
            "value_rankable_companies": len(values),
            "growth_rankable_companies": len(growth),
            "source_notes": [
                "Financial statements: SEC EDGAR companyfacts.",
                "If live SEC companyfacts is unavailable, the cloud build uses a committed SEC-derived fundamentals snapshot and marks each fallback row in source_notes.",
                "S&P 500 constituents: Wikipedia table for this MVP; replace with licensed index data in production.",
                "Market prices: Yahoo chart endpoint for this MVP; replace with licensed market data in production.",
                "Valuation: Python owner-earnings DCF using Base/Bull/Black Swan weighted fair value.",
                "Per-share valuation uses diluted weighted-average shares first; implausible SEC share tags are ignored.",
                "Top lists are de-duplicated by issuer CIK so multiple share classes do not occupy multiple ranks.",
                "Financials, Real Estate, and Utilities are flagged out until sector-specific valuation modules are added.",
            ],
            "ranking_weights": {"value": {"discount_score": 0.35, "buffett_score": 0.35, "moat_score": 0.20, "data_score": 0.10}, "growth": {"discount_score": 0.25, "lynch_score": 0.40, "fisher_score": 0.30, "data_score": 0.05}},
            "fundamentals_snapshot_generated_at": fundamentals_snapshot().get("generated_at"),
            "fallback_fundamentals_companies": sum(any("fundamentals_snapshot_fallback" in note for note in r["source_notes"]) for r in rows),
            "errors": errors,
        },
        "value_top_10": values[:10],
        "growth_top_10": growth[:10],
        "companies": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


INDEX = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>S&P 500 价值/成长监控</title><link rel="stylesheet" href="assets/styles.css"></head><body><main><header><div><p class="eyebrow">S&P 500 Monitor</p><h1>价值股与成长股每日监控</h1></div><div class="stamp" id="stamp">Loading...</div></header><section class="grid"><article><h2>价值股前十</h2><div id="value"></div></article><article><h2>成长股前十</h2><div id="growth"></div></article></section><section><div class="toolbar"><h2>全量样本</h2><input id="q" placeholder="搜索代码、公司或行业"></div><div id="all"></div></section></main><script src="assets/app.js"></script></body></html>"""
CSS = """:root{color-scheme:light;--ink:#172026;--muted:#65727c;--line:#d9e0e5;--paper:#f8fafb;--panel:#fff;--blue:#255f85;--green:#21725d}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}main{max-width:1180px;margin:auto;padding:28px 18px 48px}header{display:flex;justify-content:space-between;gap:18px;align-items:end;margin-bottom:22px}h1{margin:.1rem 0 0;font-size:clamp(30px,5vw,54px);line-height:1.02}h2{margin:0 0 14px;font-size:20px}.eyebrow{margin:0;color:var(--green);font-weight:700;letter-spacing:.08em;text-transform:uppercase}.stamp{color:var(--muted);text-align:right}section,article{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:18px;box-shadow:0 10px 30px #1720260a}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-bottom:16px;background:transparent;border:0;box-shadow:none;padding:0}.row{display:grid;grid-template-columns:44px 1fr auto;gap:12px;align-items:center;padding:12px 0;border-top:1px solid var(--line)}.row:first-child{border-top:0}.rank{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:#e7f1ed;color:var(--green);font-weight:800}.ticker{font-weight:800}.name{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.score{text-align:right}.score b{font-size:18px}.gap.pos{color:var(--green)}.gap.neg{color:#a33}.toolbar{display:flex;justify-content:space-between;gap:14px;align-items:center}input{width:min(420px,100%);padding:11px 12px;border:1px solid var(--line);border-radius:8px;font:inherit}.table{overflow:auto}table{width:100%;border-collapse:collapse;min-width:900px}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-size:12px;text-transform:uppercase}td.num{text-align:right;font-variant-numeric:tabular-nums}@media(max-width:800px){header,.toolbar{display:block}.stamp{text-align:left;margin-top:10px}.grid{grid-template-columns:1fr}.row{grid-template-columns:36px 1fr}.score{grid-column:2;text-align:left}}"""
APP = """const fmt=(x,d=1)=>x==null?'--':Number(x).toFixed(d);const pct=x=>x==null?'--':(x*100).toFixed(1)+'%';const money=x=>x==null?'--':'$'+Number(x).toFixed(2);function card(r,i){const cls=(r.fair_value_gap??0)>=0?'pos':'neg';return `<div class=row><div class=rank>${i+1}</div><div><div class=ticker>${r.ticker}</div><div class=name>${r.name}</div></div><div class=score><b>${fmt(r.value_rank_score??r.growth_rank_score)}</b><div class="gap ${cls}">${pct(r.fair_value_gap)}</div></div></div>`}function table(rows){return `<div class=table><table><thead><tr><th>代码</th><th>公司</th><th>行业</th><th>价格</th><th>公允价值</th><th>折价</th><th>价值分</th><th>成长分</th><th>状态</th></tr></thead><tbody>${rows.map(r=>`<tr><td><b>${r.ticker}</b></td><td>${r.name}</td><td>${r.sector}</td><td class=num>${money(r.price)}</td><td class=num>${money(r.fair_value)}</td><td class=num>${pct(r.fair_value_gap)}</td><td class=num>${fmt(r.value_rank_score)}</td><td class=num>${fmt(r.growth_rank_score)}</td><td>${r.status}</td></tr>`).join('')}</tbody></table></div>`}fetch('data/latest_rankings.json').then(r=>r.json()).then(d=>{document.getElementById('stamp').textContent=`更新：${new Date(d.metadata.generated_at).toLocaleString()}｜覆盖 ${d.metadata.processed_companies} 家`;document.getElementById('value').innerHTML=d.value_top_10.map(card).join('');document.getElementById('growth').innerHTML=d.growth_top_10.map(card).join('');const all=d.companies;const render=rows=>document.getElementById('all').innerHTML=table(rows);render(all);document.getElementById('q').addEventListener('input',e=>{const q=e.target.value.toLowerCase();render(all.filter(r=>[r.ticker,r.name,r.sector,r.industry].join(' ').toLowerCase().includes(q)))})});"""


def build(payload: dict[str, Any]) -> None:
    if DIST.exists():
        for path in sorted(DIST.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
    (DIST / "assets").mkdir(parents=True, exist_ok=True)
    (DIST / "data").mkdir(parents=True, exist_ok=True)
    (DIST / "index.html").write_text(INDEX, encoding="utf-8")
    (DIST / "assets" / "styles.css").write_text(CSS, encoding="utf-8")
    (DIST / "assets" / "app.js").write_text(APP, encoding="utf-8")
    (DIST / "data" / "latest_rankings.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    (DIST / "manifest.json").write_text(json.dumps({"built_at": datetime.now(timezone.utc).isoformat(), **payload["metadata"]}, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_payload(payload: dict[str, Any]) -> None:
    meta = payload["metadata"]
    if meta["processed_companies"] < 450:
        raise SystemExit(f"Refusing to deploy incomplete universe: {meta['processed_companies']} processed")
    if meta["rankable_companies"] < 20:
        raise SystemExit(f"Refusing to deploy empty or low-quality rankings: {meta['rankable_companies']} rankable")
    if len(payload["value_top_10"]) < 10 or len(payload["growth_top_10"]) < 10:
        raise SystemExit("Refusing to deploy incomplete top-10 lists")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.05)
    args = parser.parse_args()
    payload = run(args.limit, args.sleep)
    validate_payload(payload)
    build(payload)
    m = payload["metadata"]
    print(f"Built S&P 500 monitor: {m['rankable_companies']} rankable / {m['processed_companies']} processed")


if __name__ == "__main__":
    main()
