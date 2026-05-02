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
EMBEDDED_FUNDAMENTALS_SNAPSHOT_B64 = ""
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
STOOQ_URL = "https://stooq.com/q/l/?s={ticker}.us&f=sd2t2ohlcv&h&e=csv"
SHILLER_PE_URL = "https://www.multpl.com/shiller-pe"
CNN_FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
SEC_UA = os.environ.get("SEC_USER_AGENT", "sp500-monitor/0.1 contact@example.com")
PREFER_FUNDAMENTALS_SNAPSHOT = os.environ.get("PREFER_FUNDAMENTALS_SNAPSHOT") == "1"
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


def cache_json(name: str, url: str, hours: float, headers: dict[str, str], timeout: int = 30, attempts: int = 3) -> Any:
    path = CACHE / name
    if path.exists() and datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < timedelta(hours=hours):
        return json.loads(path.read_text())
    payload = json.loads(get(url, headers, timeout=timeout, attempts=attempts).decode("utf-8", "replace"))
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
                    ans.append({**item, "_tag": tag, "_unit": key})
    return ans


def val(item: dict[str, Any] | None) -> float | None:
    try:
        return None if item is None else float(item["val"])
    except (KeyError, TypeError, ValueError):
        return None


def fact_audit(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {
        "tag": item.get("_tag"),
        "unit": item.get("_unit"),
        "value": val(item),
        "form": item.get("form"),
        "fy": item.get("fy"),
        "fp": item.get("fp"),
        "start": item.get("start"),
        "end": item.get("end"),
        "filed": item.get("filed"),
        "accn": item.get("accn"),
    }


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
        elif EMBEDDED_FUNDAMENTALS_SNAPSHOT_B64:
            raw = base64.b64decode(EMBEDDED_FUNDAMENTALS_SNAPSHOT_B64)
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
    flow_items = {k: annual_fact(us, tags) for k, tags in FLOW.items()}
    instant_items = {k: instant_fact(us, tags) for k, tags in INST.items()}
    shares_outstanding_item = instant_fact(dei, ["EntityCommonStockSharesOutstanding"], "shares")
    diluted_shares_item = annual_fact(us, ["WeightedAverageNumberOfDilutedSharesOutstanding"], "shares")
    f = {k: val(item) for k, item in flow_items.items()}
    i = {k: val(item) for k, item in instant_items.items()}
    debt = sum(x for x in [i.get("debt"), i.get("long_debt")] if x is not None) or None
    revenue_history = []
    by_year: dict[int, dict[str, Any]] = {}
    for item in [x for x in candidates(us, FLOW["revenue"]) if annual(x)]:
        if item.get("fy") is not None:
            y = int(item["fy"])
            if y not in by_year or latest([item, by_year[y]]) is item:
                by_year[y] = item
    for y in sorted(by_year):
        revenue_history.append({"fy": y, "value": val(by_year[y]), "source": fact_audit(by_year[y])})
    cfo, capex, ni, da = f.get("cfo"), f.get("capex"), f.get("net_income"), f.get("da")
    if cfo is not None and capex is not None:
        owner_earnings = cfo - abs(capex)
        owner_formula = "cfo - abs(capex)"
    elif ni is not None and da is not None:
        owner_earnings = ni + da
        owner_formula = "net_income + depreciation_amortization"
    else:
        owner_earnings = None
        owner_formula = "unavailable"
    return {
        **f,
        **i,
        "debt": debt,
        "revenue_history": revenue_history,
        "revenue_cagr_3y": cagr(revenue_history),
        "shares_outstanding": val(shares_outstanding_item),
        "diluted_shares": val(diluted_shares_item),
        "owner_earnings": owner_earnings,
        "data_audit": {
            "source": "SEC EDGAR companyfacts",
            "taxonomy": {"financials": "us-gaap", "shares_outstanding": "dei"},
            "selected_facts": {
                **{k: fact_audit(item) for k, item in flow_items.items()},
                **{k: fact_audit(item) for k, item in instant_items.items()},
                "shares_outstanding": fact_audit(shares_outstanding_item),
                "diluted_shares": fact_audit(diluted_shares_item),
            },
            "owner_earnings_formula": owner_formula,
            "owner_earnings_inputs": {
                "cfo": cfo,
                "capex": capex,
                "net_income": ni,
                "depreciation_amortization": da,
            },
            "revenue_history": revenue_history[-5:],
        },
    }


def price(ticker: str) -> dict[str, Any]:
    try:
        p = cache_json(f"price_{ticker}.json", YAHOO_URL.format(ticker=quote(ticker)), 0.25, {"User-Agent": "Mozilla/5.0"}, timeout=6, attempts=2)
        result = (p.get("chart", {}).get("result") or [{}])[0]
        meta = result.get("meta", {})
        px = meta.get("regularMarketPrice")
        ts = meta.get("regularMarketTime")
        if px is None:
            closes = ((result.get("indicators", {}).get("quote") or [{}])[0].get("close") or [])
            px = next((x for x in reversed(closes) if x is not None), None)
        if px is None:
            raise RuntimeError("missing_yahoo_price")
        return {
            "price": float(px),
            "currency": meta.get("currency") or "USD",
            "market_time": datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None,
            "price_source": "Yahoo chart endpoint",
        }
    except Exception as yahoo_exc:  # noqa: BLE001 - fall through to backup quote source
        symbol = ticker.replace("-", ".").lower()
        raw = get(STOOQ_URL.format(ticker=quote(symbol)), {"User-Agent": "Mozilla/5.0", "Accept": "text/csv"}, timeout=20).decode("utf-8", "replace")
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(lines) < 2:
            raise RuntimeError(f"missing_price;yahoo={yahoo_exc}") from yahoo_exc
        fields = [x.strip() for x in lines[1].split(",")]
        if len(fields) < 7 or fields[6].upper() == "N/D":
            raise RuntimeError(f"missing_stooq_price;yahoo={yahoo_exc}") from yahoo_exc
        market_time = None
        if fields[1] != "N/D" and fields[2] != "N/D":
            try:
                market_time = datetime.fromisoformat(f"{fields[1]}T{fields[2]}+00:00").isoformat()
            except ValueError:
                market_time = None
        return {
            "price": float(fields[6]),
            "currency": "USD",
            "market_time": market_time,
            "price_source": "Stooq daily quote fallback",
        }


def shiller_pe() -> dict[str, Any]:
    html = get(SHILLER_PE_URL, {"User-Agent": "Mozilla/5.0"}, timeout=20).decode("utf-8", "replace")
    current = re.search(r'id="current".*?<b>Current.*?</b>\s*([0-9]+(?:\.[0-9]+)?)', html, re.S)
    timestamp = re.search(r'<div id="timestamp">\s*([^<]+?)\s*</div>', html, re.S)
    if not current:
        raise RuntimeError("missing_shiller_pe")
    return {
        "name": "S&P 500 Shiller PE",
        "value": round(float(current.group(1)), 2),
        "as_of": clean(timestamp.group(1)) if timestamp else None,
        "source": SHILLER_PE_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def cnn_fear_greed() -> dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "https://edition.cnn.com/",
        "Accept": "application/json",
    }
    data = json.loads(get(CNN_FEAR_GREED_URL, headers, timeout=20).decode("utf-8", "replace"))
    fg = data.get("fear_and_greed") or {}
    if fg.get("score") is None:
        raise RuntimeError("missing_cnn_fear_greed_score")
    return {
        "name": "CNN Fear & Greed Index",
        "value": round(float(fg["score"]), 1),
        "rating": fg.get("rating"),
        "as_of": fg.get("timestamp"),
        "source": "https://edition.cnn.com/markets/fear-and-greed",
        "api_source": CNN_FEAR_GREED_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def market_context() -> dict[str, Any]:
    out: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    for key, fn in [("shiller_pe", shiller_pe), ("cnn_fear_greed", cnn_fear_greed)]:
        try:
            out[key] = fn()
        except Exception as exc:  # noqa: BLE001 - show unavailable instead of inventing a macro value
            out[key] = None
            errors.append({"source": key, "error": f"{type(exc).__name__}:{exc}"})
    out["errors"] = errors
    return out


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


def rnd(x: float | None, n: int = 4) -> float | None:
    return None if x is None or not math.isfinite(x) else round(x, n)


def unavailable_audit(company: Company, err: str | None) -> dict[str, Any]:
    return {
        "ticker": company.ticker,
        "cik": company.cik,
        "data_sources": {
            "financials": "SEC EDGAR companyfacts",
            "snapshot_generated_at": fundamentals_snapshot().get("generated_at"),
        },
        "source_quality": {
            "status": "not_auditable_in_current_run",
            "reason": err or "missing fundamentals or price",
        },
        "missing_inputs": ["price", "shares", "owner_earnings", "revenue_cagr_3y"],
        "valuation": {"method": "55% Base + 20% Bull + 25% Black Swan owner-earnings DCF"},
    }


def audit_payload(
    company: Company,
    f: dict[str, Any] | None,
    q: dict[str, Any] | None,
    sh: float | None,
    px: float | None,
    market_cap: float | None,
    fair: float | None,
    gap: float | None,
    scenarios: dict[str, Any],
    scores: dict[str, float | None],
    status: str,
    notes: list[str],
    risks: list[str],
    supported: bool,
) -> dict[str, Any]:
    data_audit = (f or {}).get("data_audit") or {}
    selected_facts = {k: v for k, v in (data_audit.get("selected_facts") or {}).items() if v}
    inputs = {
        "price": px,
        "shares": sh,
        "market_cap": market_cap,
        "revenue": (f or {}).get("revenue"),
        "owner_earnings": (f or {}).get("owner_earnings"),
        "cash": (f or {}).get("cash"),
        "debt": (f or {}).get("debt"),
        "revenue_cagr_3y": (f or {}).get("revenue_cagr_3y"),
        "net_income": (f or {}).get("net_income"),
        "operating_income": (f or {}).get("operating_income"),
        "gross_profit": (f or {}).get("gross_profit"),
        "assets": (f or {}).get("assets"),
        "liabilities": (f or {}).get("liabilities"),
        "equity": (f or {}).get("equity"),
    }
    missing = [k for k, v in inputs.items() if v is None]
    owner_inputs = data_audit.get("owner_earnings_inputs") or {
        "cfo": (f or {}).get("cfo"),
        "capex": (f or {}).get("capex"),
        "net_income": (f or {}).get("net_income"),
        "depreciation_amortization": (f or {}).get("da"),
    }
    source_quality = {
        "status": "tag_level_audit_available" if selected_facts else "legacy_snapshot_without_tag_level_audit",
        "note": None if selected_facts else "当前 SEC 快照早于逐字段审计功能；下次 SEC bulk 快照刷新后会显示每个字段对应的 tag、filed date 和 accn。",
    }
    return {
        "ticker": company.ticker,
        "cik": company.cik,
        "issuer_key": company.cik or company.name.lower(),
        "data_sources": {
            "financials": data_audit.get("source") or "SEC EDGAR companyfacts snapshot",
            "snapshot_generated_at": fundamentals_snapshot().get("generated_at"),
            "price": q.get("price_source") if q else None,
            "market_time": q.get("market_time") if q else None,
        },
        "source_quality": source_quality,
        "sec_facts": selected_facts,
        "owner_earnings": {
            "formula": data_audit.get("owner_earnings_formula") or ("cfo - abs(capex)" if owner_inputs.get("cfo") is not None and owner_inputs.get("capex") is not None else "net_income + depreciation_amortization fallback if cfo/capex unavailable"),
            "inputs": {k: rnd(v) for k, v in owner_inputs.items()},
            "value": rnd((f or {}).get("owner_earnings")),
        },
        "valuation": {
            "method": "55% Base + 20% Bull + 25% Black Swan owner-earnings DCF",
            "inputs": {k: rnd(v, 6 if k == "revenue_cagr_3y" else 4) for k, v in inputs.items()},
            "scenarios": scenarios,
            "weighted_fair_value": rnd(fair),
            "fair_value_gap": rnd(gap, 6),
        },
        "score_breakdown": {
            "value_formula": "35% discount + 35% Buffett + 20% moat + 10% data completeness",
            "growth_formula": "25% discount + 40% Lynch + 30% Fisher + 5% data completeness",
            "components": {k: rnd(v) for k, v in scores.items()},
        },
        "quality_checks": {
            "status": status,
            "sector_model_supported": supported,
            "missing_inputs": missing,
            "source_notes": notes,
            "risk_tags": sorted(set(risks)),
        },
    }


def score(company: Company, f: dict[str, Any] | None, q: dict[str, Any] | None, err: str | None) -> dict[str, Any]:
    if err in {"fundamentals_snapshot_not_in_mvp_candidate_set", "fundamentals_error:RuntimeError:prefer_fundamentals_snapshot"}:
        return {
            "ticker": company.ticker,
            "name": company.name,
            "cik": company.cik,
            "issuer_key": company.cik or company.name.lower(),
            "sector": company.sector,
            "industry": company.industry,
            "price": None,
            "currency": None,
            "market_time": None,
            "price_source": None,
            "fair_value": None,
            "fair_value_method": "55% Base + 20% Bull + 25% Black Swan owner-earnings DCF",
            "fair_value_gap": None,
            "value_rank_score": None,
            "growth_rank_score": None,
            "buffett_score": None,
            "moat_score": None,
            "lynch_score": None,
            "fisher_score": None,
            "discount_score": None,
            "data_score": 0,
            "revenue_cagr_3y": None,
            "owner_earnings_yield": None,
            "fcf_margin": None,
            "operating_margin": None,
            "gross_margin": None,
            "roe": None,
            "debt_to_assets": None,
            "scenarios": {},
            "audit": unavailable_audit(company, err),
            "source_notes": ["not_in_current_mvp_candidate_set"],
            "risk_tags": ["mvp_candidate_filter"],
            "status": "not_in_mvp_candidate_set",
        }
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
    if gap is not None and gap < 0:
        risks.append("priced_above_weighted_fair_value")
    if value_score is not None or growth_score is not None:
        status = "rankable"
    elif not supported:
        status = "sector_model_limit"
    elif fair is not None and gap is not None and data_score >= 75:
        status = "fails_current_screen"
    else:
        status = "insufficient_financial_data"
    scores = {
        "discount_score": discount_score,
        "buffett_score": buffett,
        "moat_score": moat,
        "lynch_score": lynch,
        "fisher_score": fisher,
        "data_score": data_score,
        "value_rank_score": value_score,
        "growth_rank_score": growth_score,
        "owner_earnings_yield": oe_yield,
        "fcf_margin": fcf_margin,
        "operating_margin": op_margin,
        "gross_margin": gross_margin,
        "roe": roe,
        "debt_to_assets": debt_assets,
    }
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
        "price_source": q.get("price_source") if q else None,
        "fair_value": rnd(fair),
        "fair_value_method": "55% Base + 20% Bull + 25% Black Swan owner-earnings DCF",
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
        "audit": audit_payload(company, f, q, sh, px, market_cap, fair, gap, scenarios, scores, status, notes, risks, supported),
        "source_notes": notes,
        "risk_tags": sorted(set(risks)),
        "status": status,
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
            if PREFER_FUNDAMENTALS_SNAPSHOT:
                f = snapshot_fundamentals(c.cik)
                if f:
                    err = "fundamentals_snapshot_preferred"
                else:
                    raise RuntimeError("missing_fundamentals_snapshot")
            else:
                f = fundamentals(facts(c.cik))
                time.sleep(pause)
        except Exception as exc:  # noqa: BLE001
            fallback = None if PREFER_FUNDAMENTALS_SNAPSHOT else (snapshot_fundamentals(c.cik) if c.cik else None)
            if fallback:
                f = fallback
                if str(exc) == "prefer_fundamentals_snapshot":
                    err = "fundamentals_snapshot_preferred"
                else:
                    err = f"fundamentals_snapshot_fallback:live_sec_{type(exc).__name__}:{exc}"
                    errors.append({"ticker": c.ticker, "stage": "fundamentals_live", "error": str(exc), "fallback": "fundamentals_snapshot"})
            elif PREFER_FUNDAMENTALS_SNAPSHOT and str(exc) == "missing_fundamentals_snapshot":
                err = "fundamentals_snapshot_not_in_mvp_candidate_set"
            elif str(exc) == "prefer_fundamentals_snapshot":
                err = "fundamentals_snapshot_not_in_mvp_candidate_set"
            else:
                err = f"fundamentals_error:{type(exc).__name__}:{exc}"
                errors.append({"ticker": c.ticker, "stage": "fundamentals", "error": str(exc)})
        if not (PREFER_FUNDAMENTALS_SNAPSHOT and f is None):
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
    context = market_context()
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
                "Market prices: Yahoo chart endpoint with Stooq daily quote fallback for this MVP; replace with licensed market data in production.",
                "Market context: S&P 500 Shiller PE from Multpl; CNN Fear & Greed from CNN's public dataviz JSON endpoint.",
                "Valuation: Python owner-earnings DCF using Base/Bull/Black Swan weighted fair value.",
                "Audit: each company row includes price source, snapshot source, owner-earnings inputs, DCF scenarios, score components, missing inputs, and SEC tag-level provenance when the snapshot was built with the audit-enabled parser.",
                "Per-share valuation uses diluted weighted-average shares first; implausible SEC share tags are ignored.",
                "Top lists are de-duplicated by issuer CIK so multiple share classes do not occupy multiple ranks.",
                "Financials, Real Estate, and Utilities are flagged out until sector-specific valuation modules are added.",
            ],
            "ranking_weights": {"value": {"discount_score": 0.35, "buffett_score": 0.35, "moat_score": 0.20, "data_score": 0.10}, "growth": {"discount_score": 0.25, "lynch_score": 0.40, "fisher_score": 0.30, "data_score": 0.05}},
            "score_definitions": {
                "weighted_fair_value": "55% Base + 20% Bull + 25% Black Swan owner-earnings DCF per share.",
                "discount_score": "Fair-value gap mapped from -20% to +80% into a 0-100 score.",
                "value_rank_score": "35% discount_score + 35% Buffett quality + 20% moat + 10% data completeness.",
                "growth_rank_score": "25% discount_score + 40% Peter Lynch growth/value fit + 30% Fisher growth quality + 5% data completeness.",
            },
            "market_context": context,
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


INDEX = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>S&P 500 价值/成长监控</title><link rel="stylesheet" href="assets/styles.css"></head><body><main><header><div><p class="eyebrow">S&P 500 Monitor</p><h1>价值股与成长股每日监控</h1></div><div class="stamp" id="stamp">Loading...</div></header><section class="macro" id="macro"></section><section class="explain"><div><h2>评分口径</h2><p>加权公允价值 = 55% 基准情景 + 20% 乐观情景 + 25% 黑天鹅情景，均由 Python 所有者收益 DCF 逐股计算。</p></div><div class="formula"><b>价值分</b><span>35% 折价 + 35% 巴菲特质量 + 20% 护城河 + 10% 数据完整度</span></div><div class="formula"><b>成长分</b><span>25% 折价 + 40% 彼得林奇 + 30% 费雪 + 5% 数据完整度</span></div></section><section class="grid"><article><h2>价值股前十</h2><div id="value"></div></article><article><h2>成长股前十</h2><div id="growth"></div></article></section><section><div class="toolbar"><h2>全量样本</h2><input id="q" placeholder="搜索代码、公司、行业或状态"></div><div id="all"></div></section></main><script src="assets/app.js"></script></body></html>"""
CSS = """:root{color-scheme:light;--ink:#172026;--muted:#65727c;--line:#d9e0e5;--paper:#f8fafb;--panel:#fff;--green:#21725d;--blue:#255f85;--red:#a33;--amber:#9a6a18}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}main{max-width:1240px;margin:auto;padding:28px 18px 48px}header{display:flex;justify-content:space-between;gap:18px;align-items:end;margin-bottom:16px}h1{margin:.1rem 0 0;font-size:clamp(30px,5vw,52px);line-height:1.02;letter-spacing:0}h2{margin:0 0 14px;font-size:20px}.eyebrow{margin:0;color:var(--green);font-weight:700;letter-spacing:0;text-transform:uppercase}.stamp{color:var(--muted);text-align:right}.macro{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:16px;background:transparent;border:0;box-shadow:none;padding:0}.tile,section,article{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:18px;box-shadow:0 10px 30px #1720260a}.tile{min-height:108px}.tile .label{color:var(--muted);font-size:13px}.tile .big{font-size:30px;font-weight:800;line-height:1.1;margin-top:8px}.tile .sub{color:var(--muted);margin-top:6px}.explain{display:grid;grid-template-columns:1.25fr 1fr 1fr;gap:14px;margin-bottom:16px}.explain p{margin:0;color:var(--muted)}.formula{border-left:3px solid #d9e0e5;padding-left:12px}.formula b{display:block;margin-bottom:4px}.formula span{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-bottom:16px;background:transparent;border:0;box-shadow:none;padding:0}.row{display:grid;grid-template-columns:44px 1fr auto;gap:12px;align-items:center;padding:12px 0;border-top:1px solid var(--line)}.row:first-child{border-top:0}.rank{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:#e7f1ed;color:var(--green);font-weight:800}.ticker{font-weight:800}.name{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:330px}.score{text-align:right}.score b{font-size:18px}.metrics{grid-column:2/4;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:2px}.metric{background:#f4f7f8;border:1px solid var(--line);border-radius:8px;padding:8px}.metric span{display:block;color:var(--muted);font-size:12px}.metric b{font-size:14px}.components{grid-column:2/4;color:var(--muted);font-size:12px}.gap.pos{color:var(--green)}.gap.neg{color:var(--red)}.toolbar{display:flex;justify-content:space-between;gap:14px;align-items:center}input{width:min(420px,100%);padding:11px 12px;border:1px solid var(--line);border-radius:8px;font:inherit}.table{overflow:auto}table{width:100%;border-collapse:collapse;min-width:1160px}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-size:12px;text-transform:uppercase}td.num{text-align:right;font-variant-numeric:tabular-nums}.badge{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:3px 8px;font-size:12px;white-space:nowrap}.badge.ok{color:var(--green);background:#e7f1ed}.badge.warn{color:var(--amber);background:#fff5df}.badge.muted{color:var(--muted);background:#f4f7f8}.audit{grid-column:2/4;margin-top:8px}.audit summary{cursor:pointer;color:var(--blue);font-weight:700;list-style:none}.audit summary::-webkit-details-marker{display:none}.auditPanel{margin-top:10px;padding:12px;border:1px solid var(--line);border-radius:8px;background:#fbfcfd;color:var(--ink);min-width:min(980px,82vw)}.auditPanel h3{margin:0 0 6px;font-size:13px;color:var(--ink)}.auditPanel p{margin:0 0 10px}.auditGrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:12px}.auditFacts{min-width:860px;margin-bottom:12px;background:#fff}.auditFacts th,.auditFacts td{font-size:12px;padding:7px}.muted,.sub{color:var(--muted)}.auditPanel ul{margin:0 0 8px;padding-left:18px}@media(max-width:900px){header,.toolbar{display:block}.stamp{text-align:left;margin-top:10px}.macro,.explain,.grid{grid-template-columns:1fr}.row{grid-template-columns:36px 1fr}.score{grid-column:2;text-align:left}.metrics,.components,.audit{grid-column:1/3}.metrics,.auditGrid{grid-template-columns:1fr}.name{max-width:100%}.auditPanel{min-width:0}}"""
APP = """const fmt=(x,d=1)=>x==null?'--':Number(x).toFixed(d);const pct=x=>x==null?'--':(x*100).toFixed(1)+'%';const rate=x=>x==null?'--':(x*100).toFixed(2)+'%';const money=x=>x==null?'--':'$'+Number(x).toFixed(2);const big=x=>x==null?'--':(Math.abs(Number(x))>=1e9?'$'+(Number(x)/1e9).toFixed(2)+'B':Math.abs(Number(x))>=1e6?'$'+(Number(x)/1e6).toFixed(2)+'M':'$'+Number(x).toFixed(2));const dt=x=>x?new Date(x).toLocaleString():'--';const esc=x=>String(x??'--').replace(/[&<>\"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[m]));const statusMap={rankable:'可排名',not_in_mvp_candidate_set:'候选池外',sector_model_limit:'行业模型暂不覆盖',fails_current_screen:'未通过当前筛选',insufficient_financial_data:'财务资料不足'};const statusText=r=>statusMap[r.status]||'待检查';const badge=r=>r.status==='rankable'?'ok':r.status==='insufficient_financial_data'?'warn':'muted';const comp=r=>`折价 ${fmt(r.discount_score)} / 巴菲特 ${fmt(r.buffett_score)} / 护城河 ${fmt(r.moat_score)} / 林奇 ${fmt(r.lynch_score)} / 费雪 ${fmt(r.fisher_score)} / 数据 ${fmt(r.data_score)}`;
function macro(m){const s=m.market_context?.shiller_pe;const f=m.market_context?.cnn_fear_greed;const err=(m.market_context?.errors||[]).length;return `<div class=tile><div class=label>S&P 500 Shiller PE</div><div class=big>${s?fmt(s.value,2):'--'}</div><div class=sub>${esc(s?.as_of||'未获取')} · Multpl</div></div><div class=tile><div class=label>CNN Fear & Greed</div><div class=big>${f?fmt(f.value,1):'--'}</div><div class=sub>${esc(f?.rating||'未获取')} · ${f?.as_of?dt(f.as_of):'CNN'}</div></div><div class=tile><div class=label>本次刷新</div><div class=big>${m.rankable_companies}/${m.processed_companies}</div><div class=sub>可排名 / 覆盖公司${err?` · 宏观源错误 ${err}`:''}</div></div>`}
function factRows(facts){const rows=Object.entries(facts||{}).slice(0,16);if(!rows.length)return '<p class=muted>当前快照暂无逐字段 SEC tag 审计；下一次 SEC bulk 快照刷新后自动补齐。</p>';return `<table class=auditFacts><thead><tr><th>字段</th><th>SEC tag</th><th>值</th><th>期间</th><th>Filed</th><th>Accn</th></tr></thead><tbody>${rows.map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(v.tag)}</td><td class=num>${big(v.value)}</td><td>${esc([v.form,v.fy,v.fp].filter(Boolean).join(' '))}<br><span class=sub>${esc(v.start||'')} ${v.end?'→ '+esc(v.end):''}</span></td><td>${esc(v.filed)}</td><td>${esc(v.accn)}</td></tr>`).join('')}</tbody></table>`}
function scenarioRows(s){const rows=Object.entries(s||{});if(!rows.length)return '<p class=muted>本行业或本公司数据不足，未生成通用 owner-earnings DCF。</p>';return `<table class=auditFacts><thead><tr><th>情景</th><th>权重</th><th>增长</th><th>折现率</th><th>永续增长</th><th>每股价值</th></tr></thead><tbody>${rows.map(([k,v])=>`<tr><td>${esc(k)}</td><td class=num>${pct(v.weight)}</td><td class=num>${pct(v.growth)}</td><td class=num>${pct(v.discount_rate)}</td><td class=num>${pct(v.terminal_growth)}</td><td class=num>${money(v.per_share)}</td></tr>`).join('')}</tbody></table>`}
function audit(r){const a=r.audit||{};const q=a.quality_checks||{};const v=a.valuation||{};const oi=a.owner_earnings||{};const sb=a.score_breakdown||{};const c=sb.components||{};const src=a.data_sources||{};const missing=(q.missing_inputs||[]).slice(0,12).map(esc).join(', ')||'无关键缺口';const notes=(q.source_notes||[]).filter(Boolean).map(x=>`<li>${esc(x)}</li>`).join('')||'<li>无</li>';const risks=(q.risk_tags||[]).filter(Boolean).map(x=>`<li>${esc(x)}</li>`).join('')||'<li>无</li>';return `<div class=auditPanel><div class=auditGrid><div><h3>数据来源</h3><p>财务：${esc(src.financials)}<br>SEC 快照：${esc(src.snapshot_generated_at)}<br>价格：${esc(src.price)}<br>市场时间：${esc(src.market_time)}</p><p class=muted>${esc(a.source_quality?.note||a.source_quality?.status||'')}</p></div><div><h3>Owner earnings</h3><p>公式：${esc(oi.formula)}<br>结果：${big(oi.value)}<br>CFO：${big(oi.inputs?.cfo)} · Capex：${big(oi.inputs?.capex)}<br>NI：${big(oi.inputs?.net_income)} · D&A：${big(oi.inputs?.depreciation_amortization)}</p></div><div><h3>模型输入</h3><p>股价：${money(v.inputs?.price)} · 股数：${fmt(v.inputs?.shares,0)}<br>现金：${big(v.inputs?.cash)} · 债务：${big(v.inputs?.debt)}<br>收入 CAGR：${rate(v.inputs?.revenue_cagr_3y)}<br>缺口：${esc(missing)}</p></div><div><h3>分数拆解</h3><p>${esc(sb.value_formula)}<br>${esc(sb.growth_formula)}</p><p>折价 ${fmt(c.discount_score)} · 巴菲特 ${fmt(c.buffett_score)} · 护城河 ${fmt(c.moat_score)} · 林奇 ${fmt(c.lynch_score)} · 费雪 ${fmt(c.fisher_score)} · 数据 ${fmt(c.data_score)}</p></div></div><h3>DCF 三情景</h3>${scenarioRows(v.scenarios)}<h3>SEC 字段追溯</h3>${factRows(a.sec_facts)}<div class=auditGrid><div><h3>来源备注</h3><ul>${notes}</ul></div><div><h3>风险标签</h3><ul>${risks}</ul></div></div></div>`}
function card(r,i){const cls=(r.fair_value_gap??0)>=0?'pos':'neg';const score=r.value_rank_score??r.growth_rank_score;return `<div class=row><div class=rank>${i+1}</div><div><div class=ticker>${esc(r.ticker)}</div><div class=name>${esc(r.name)}</div></div><div class=score><b>${fmt(score)}</b><div class="gap ${cls}">${pct(r.fair_value_gap)}</div></div><div class=metrics><div class=metric><span>最新价格</span><b>${money(r.price)}</b></div><div class=metric><span>加权公允价值</span><b>${money(r.fair_value)}</b></div><div class=metric><span>价值分</span><b>${fmt(r.value_rank_score)}</b></div><div class=metric><span>成长分</span><b>${fmt(r.growth_rank_score)}</b></div></div><div class=components>${comp(r)}</div><details class=audit><summary>审计明细</summary>${audit(r)}</details></div>`}
function table(rows){return `<div class=table><table><thead><tr><th>代码</th><th>公司</th><th>行业</th><th>最新价格</th><th>加权公允价值</th><th>折价</th><th>价值分</th><th>成长分</th><th>巴菲特</th><th>护城河</th><th>林奇</th><th>费雪</th><th>数据</th><th>状态</th></tr></thead><tbody>${rows.map(r=>`<tr><td><b>${esc(r.ticker)}</b><details class=audit><summary>审计</summary>${audit(r)}</details></td><td>${esc(r.name)}<br><span class=sub>${esc(r.price_source||'')}</span></td><td>${esc(r.sector)}</td><td class=num>${money(r.price)}</td><td class=num>${money(r.fair_value)}</td><td class=num>${pct(r.fair_value_gap)}</td><td class=num>${fmt(r.value_rank_score)}</td><td class=num>${fmt(r.growth_rank_score)}</td><td class=num>${fmt(r.buffett_score)}</td><td class=num>${fmt(r.moat_score)}</td><td class=num>${fmt(r.lynch_score)}</td><td class=num>${fmt(r.fisher_score)}</td><td class=num>${fmt(r.data_score)}</td><td><span class="badge ${badge(r)}">${statusText(r)}</span></td></tr>`).join('')}</tbody></table></div>`}
fetch('data/latest_rankings.json').then(r=>r.json()).then(d=>{document.getElementById('stamp').textContent=`更新：${new Date(d.metadata.generated_at).toLocaleString()} · 快照：${d.metadata.fundamentals_snapshot_generated_at||'live SEC'}`;document.getElementById('macro').innerHTML=macro(d.metadata);document.getElementById('value').innerHTML=d.value_top_10.map(card).join('');document.getElementById('growth').innerHTML=d.growth_top_10.map(card).join('');const all=d.companies.slice().sort((a,b)=>(b.status==='rankable')-(a.status==='rankable')||(b.value_rank_score??b.growth_rank_score??-1)-(a.value_rank_score??a.growth_rank_score??-1));const render=rows=>document.getElementById('all').innerHTML=table(rows);render(all);document.getElementById('q').addEventListener('input',e=>{const q=e.target.value.toLowerCase();render(all.filter(r=>[r.ticker,r.name,r.sector,r.industry,statusText(r)].join(' ').toLowerCase().includes(q)))})});"""


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
