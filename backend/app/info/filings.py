"""Filings — EDINET (Japan, FSA; EDINET_API_KEY) and SEC EDGAR (US; SEC_USER_AGENT). Parsers are pure functions.

EDINET v2: /api/v2/documents.json?date=YYYY-MM-DD&type=2 → results with docID, secCode (5 digits), filerName,
docDescription, docTypeCode, submitDateTime, edinetCode, issuerEdinetCode, subjectEdinetCode, withdrawalStatus.
For 大量保有報告書 the company concerned is the issuer / subject, not the filer: the EDINET code list (CSV in a zip)
maps EDINET codes to security codes.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from typing import Any

EDINET = "https://api.edinet-fsa.go.jp/api/v2"
EDINET_CODES = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# what matters to an equity analyst, in order of how it is shown
KINDS = [("大量保有", ("大量保有報告書", "変更報告書")), ("自己株買い", ("自己株券買付状況",)), ("公開買付", ("公開買付",)),
         ("有価証券報告書", ("有価証券報告書",)), ("半期・四半期", ("半期報告書", "四半期報告書")), ("臨時報告書", ("臨時報告書",)),
         ("訂正", ("訂正",))]


def edinet_kind(desc: str) -> str:
    d = desc or ""
    if "訂正" in d and not any(w in d for w in ("大量保有", "変更報告書")):
        return "訂正"
    for k, words in KINDS:
        if any(w in d for w in words):
            return k
    return "その他"


def parse_edinet_list(obj: dict[str, Any]) -> list[dict[str, Any]]:
    meta = obj.get("metadata") or {}
    if str(meta.get("status", obj.get("statusCode", "200"))) not in ("200",):
        raise ValueError(f"EDINET: {meta.get('message') or obj.get('message') or meta}")
    out = []
    for r in obj.get("results") or []:
        if str(r.get("withdrawalStatus") or "0") != "0":
            continue
        out.append({"doc_id": r.get("docID"), "sec_code": (r.get("secCode") or "")[:4] or None, "filer": r.get("filerName"),
                    "desc": r.get("docDescription") or "", "type": r.get("docTypeCode"), "at": (r.get("submitDateTime") or "").replace(" ", "T"),
                    "edinet": r.get("edinetCode"), "issuer": r.get("issuerEdinetCode"), "subject": r.get("subjectEdinetCode"),
                    "kind": edinet_kind(r.get("docDescription") or "")})
    return out


def parse_edinet_codes(content: bytes) -> dict[str, str]:
    """EDINET code list (zip with one CSV in cp932; first line is a title) → {EDINET code: 4-character security code}."""
    zf = zipfile.ZipFile(io.BytesIO(content))
    name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
    text = zf.read(name).decode("cp932", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    head_i = next(i for i, r in enumerate(rows[:5]) if any("ＥＤＩＮＥＴコード" in c or "EDINETコード" in c for c in r))
    head = rows[head_i]
    ci = next(i for i, c in enumerate(head) if "ＥＤＩＮＥＴコード" in c or "EDINETコード" in c)
    si = next(i for i, c in enumerate(head) if "証券コード" in c)
    out = {}
    for r in rows[head_i + 1:]:
        if len(r) > max(ci, si) and r[si].strip():
            out[r[ci].strip()] = r[si].strip()[:4]
    return out


def edinet_ticker(doc: dict[str, Any], codes: dict[str, str]) -> str | None:
    """The company a filing is about: the subject / issuer when there is one (大量保有), else the filer."""
    for k in ("subject", "issuer"):
        if doc.get(k) and codes.get(doc[k]):
            return codes[doc[k]]
    return doc.get("sec_code") or (codes.get(doc.get("edinet") or "") if doc.get("edinet") else None)


def parse_sec_tickers(obj: dict[str, Any]) -> dict[str, int]:
    return {str(v["ticker"]).upper(): int(v["cik_str"]) for v in obj.values() if isinstance(v, dict) and v.get("ticker")}


SEC_FORMS = {"10-K": "年次報告", "10-Q": "四半期報告", "8-K": "臨時報告", "4": "インサイダー取引", "SC 13D": "大量保有（積極）",
             "SC 13G": "大量保有（受動）", "SC 13D/A": "大量保有（積極・訂正）", "SC 13G/A": "大量保有（受動・訂正）", "DEF 14A": "株主総会",
             "S-1": "新規公開", "424B5": "目論見書", "6-K": "外国企業の臨時報告", "20-F": "外国企業の年次報告"}


def parse_sec_submissions(obj: dict[str, Any], limit: int = 40) -> list[dict[str, Any]]:
    rec = (obj.get("filings") or {}).get("recent") or {}
    forms = rec.get("form") or []
    out = []
    cik = int(obj.get("cik") or 0)
    for i, f in enumerate(forms[:200]):
        acc = (rec.get("accessionNumber") or [""] * len(forms))[i]
        doc = (rec.get("primaryDocument") or [""] * len(forms))[i]
        out.append({"form": f, "kind": SEC_FORMS.get(f, f), "date": (rec.get("filingDate") or [None] * len(forms))[i],
                    "desc": (rec.get("primaryDocDescription") or [""] * len(forms))[i] or f,
                    "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}" if acc and doc else None})
        if len(out) >= limit:
            break
    return out


def ticker_of_symbol(symbol: str) -> str:
    return symbol.split(":")[-1].upper()


def is_jp(symbol: str) -> bool:
    return symbol.upper().startswith(("TSE:", "OSE:")) or bool(re.fullmatch(r"\d{3}[0-9A-Z]", symbol))
