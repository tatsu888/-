"""Minimal Notion REST client for the coverage feature (official API, integration token).

Setup (once): create an internal integration at https://www.notion.so/my-integrations, copy its token into
.env as NOTION_TOKEN (secret — never commit), and share the 銘柄マスタ database and the ATLAS/MICRO page
with the integration (… menu → Connections). IDs go to NOTION_COVERAGE_DB / NOTION_MICRO_PAGE (or the COV
settings). API version 2022-06-28 (single-data-source databases).
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import httpx

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
CONTAINERS = {"toggle", "column_list", "column", "synced_block", "heading_1", "heading_2", "heading_3", "callout", "quote",
              "bulleted_list_item", "numbered_list_item"}
COMPANY_TITLE = re.compile(r"^\s*(\d{3}[0-9A-Z])\s*[|｜]\s*(.+?)\s*$")
GROUP_TITLE = re.compile(r"^\s*(\d{4})\s*[|｜]\s*(.+?)\s*$")


class NotionError(Exception):
    def __init__(self, msg: str, status: int = 502) -> None:
        super().__init__(msg)
        self.status = status


def plain(rich: list[dict[str, Any]] | None) -> str:
    return "".join(r.get("plain_text") or (r.get("text") or {}).get("content", "") for r in (rich or []))


def page_title(page: dict[str, Any]) -> str:
    for p in (page.get("properties") or {}).values():
        if p.get("type") == "title":
            return plain(p.get("title"))
    return ""


class NotionClient:
    def __init__(self, token: str | None = None, http: httpx.AsyncClient | None = None, delay: float = 0.34) -> None:
        self.token = token if token is not None else os.environ.get("NOTION_TOKEN", "")
        self.http = http or httpx.AsyncClient(timeout=30)
        self.delay = delay
        self.calls = 0

    async def close(self) -> None:
        await self.http.aclose()

    async def _req(self, method: str, path: str, body: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.token:
            raise NotionError("NOTION_TOKEN が未設定（.env に設定し、データベースとページをインテグレーションに共有）", 400)
        headers = {"Authorization": f"Bearer {self.token}", "Notion-Version": VERSION, "Content-Type": "application/json"}
        for attempt in range(4):
            if self.delay:
                await asyncio.sleep(self.delay)
            self.calls += 1
            try:
                r = await self.http.request(method, API + path, json=body, params=params, headers=headers)
            except httpx.HTTPError as e:
                raise NotionError(f"notion {path}: {e}") from e
            if r.status_code == 429 and attempt < 3:
                await asyncio.sleep(float(r.headers.get("Retry-After", "1")))
                continue
            if r.status_code >= 400:
                try:
                    msg = r.json().get("message", r.text)
                except ValueError:
                    msg = r.text
                raise NotionError(f"notion {method} {path}: {r.status_code} {msg}", 400 if r.status_code in (400, 401, 403, 404) else 502)
            return r.json()
        raise NotionError(f"notion {path}: rate limited")

    # ---- reads -------------------------------------------------------------------------------
    async def query_database(self, db_id: str) -> list[dict[str, Any]]:
        out, cursor = [], None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            r = await self._req("POST", f"/databases/{db_id}/query", body)
            out += r.get("results", [])
            if not r.get("has_more"):
                return out
            cursor = r.get("next_cursor")

    async def children(self, block_id: str) -> list[dict[str, Any]]:
        out, cursor = [], None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            r = await self._req("GET", f"/blocks/{block_id}/children", params=params)
            out += r.get("results", [])
            if not r.get("has_more"):
                return out
            cursor = r.get("next_cursor")

    async def child_pages(self, block_id: str, nested_depth: int = 2) -> list[dict[str, Any]]:
        """Child pages of a page, including those nested inside toggles / columns / headings."""
        out = []
        for b in await self.children(block_id):
            if b.get("type") == "child_page":
                out.append({"id": b["id"], "title": (b.get("child_page") or {}).get("title", "")})
            elif b.get("has_children") and b.get("type") in CONTAINERS and nested_depth > 0:
                out += await self.child_pages(b["id"], nested_depth - 1)
        return out

    async def company_pages(self, micro_page: str) -> dict[str, dict[str, Any]]:
        """{ticker: {id, title, group}} from ATLAS/MICRO → '<GICS> | …' pages → '<ticker> | <社名>' pages."""
        found: dict[str, dict[str, Any]] = {}
        for g in await self.child_pages(micro_page):
            if not GROUP_TITLE.match(g["title"]):
                continue
            for c in await self.child_pages(g["id"]):
                m = COMPANY_TITLE.match(c["title"])
                if m and m.group(1) not in found:
                    found[m.group(1)] = {"id": c["id"], "title": c["title"], "group": g["title"],
                                         "url": f"https://www.notion.so/{c['id'].replace('-', '')}"}
        return found

    # ---- writes ------------------------------------------------------------------------------
    async def create_page(self, parent_page: str, title: str, children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        kids = children or []
        page = await self._req("POST", "/pages", {"parent": {"page_id": parent_page},
                                                  "properties": {"title": {"title": [{"text": {"content": title}}]}},
                                                  "children": kids[:100]})
        for i in range(100, len(kids), 100):
            await self._req("PATCH", f"/blocks/{page['id']}/children", {"children": kids[i:i + 100]})
        return page

    async def update_properties(self, page_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        return await self._req("PATCH", f"/pages/{page_id}", {"properties": properties})

    async def add_database_properties(self, db_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        return await self._req("PATCH", f"/databases/{db_id}", {"properties": properties})

    async def database(self, db_id: str) -> dict[str, Any]:
        return await self._req("GET", f"/databases/{db_id}")


# ---- 銘柄マスタ rows ------------------------------------------------------------------------------
MASTER_PROPS = {"ticker": "Ticker", "name": "社名", "gics_group": "GICS産業グループ", "gics_sub": "GICS産業サブグループ",
                "topix17": "旧セクター（TOPIX17）", "fye_month": "決算期末月", "fye_uncertain": "未確定"}
EARNINGS_PROPS = {"next_date": "次回決算日", "next_title": "次回決算期"}


def parse_master_row(page: dict[str, Any], names: dict[str, str] | None = None) -> dict[str, Any] | None:
    n = {**MASTER_PROPS, **(names or {})}
    props = page.get("properties") or {}

    def val(key: str) -> Any:
        p = props.get(n[key]) or {}
        t = p.get("type")
        if t == "title":
            return plain(p.get("title")).strip()
        if t == "rich_text":
            return plain(p.get("rich_text")).strip() or None
        if t == "select":
            return (p.get("select") or {}).get("name")
        if t == "number":
            return p.get("number")
        if t == "checkbox":
            return bool(p.get("checkbox"))
        return None

    ticker = (val("ticker") or "").upper()
    if not re.fullmatch(r"\d{3}[0-9A-Z]", ticker):
        return None
    fye = val("fye_month")
    return {"ticker": ticker, "symbol": f"TSE:{ticker}", "name": val("name"), "gics_group": val("gics_group"),
            "gics_sub": val("gics_sub"), "topix17": val("topix17"),
            "fye_month": int(fye) if isinstance(fye, (int, float)) and 1 <= int(fye) <= 12 else None,
            "fye_uncertain": bool(val("fye_uncertain")), "master_page_id": page.get("id"), "master_url": page.get("url")}
