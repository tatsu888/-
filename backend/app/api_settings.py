"""Settings: API keys written to the local .env of the PC that runs the terminal (git-ignored), applied at once.

Keys are never returned in full (masked) and never logged. The path can be changed with TERMINAL_ENV_FILE (tests).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/settings")


def env_path() -> Path:
    return Path(os.environ.get("TERMINAL_ENV_FILE") or Path(__file__).resolve().parents[2] / ".env")


def _estat(v: str) -> str | None:
    from .econ.sources import estat_app_id_problem
    return estat_app_id_problem(v)


def _pattern(rx: str, msg: str) -> Callable[[str], str | None]:
    return lambda v: None if re.fullmatch(rx, v) else msg


KEYS: dict[str, tuple[str, str, Callable[[str], str | None]]] = {
    "ESTAT_APP_ID": ("e-Stat アプリケーション ID", "日本の公式統計（ECST）。e-Stat のマイページ →「API 機能」で発行", _estat),
    "FRED_API_KEY": ("FRED API キー", "任意。ECST の検索に使う（取得は鍵なしでも可）", _pattern(r"[a-z0-9]{32}", "FRED のキーは英小文字と数字 32 文字")),
    "EDINET_API_KEY": ("EDINET API キー", "金融庁 EDINET の開示（大量保有・自己株買い・有報…）。EDINET の API 利用登録で発行",
                       _pattern(r"[A-Za-z0-9]{20,64}", "EDINET のキーは英数字")),
    "SEC_USER_AGENT": ("SEC EDGAR の連絡先", "米国の開示（10-K・8-K…）。SEC の規則で「名前 メールアドレス」を送る（例: Taro Yamada taro@example.com）",
                       lambda v: None if "@" in v and len(v) >= 8 else "名前とメールアドレスを入れる（SEC の規則）"),
}


def mask(v: str | None) -> str | None:
    if not v:
        return None
    return f"{v[:4]}…{v[-4:]}" if len(v) > 10 else "設定済み"


def _quoted(value: str) -> str:
    """Quote a value that the .env reader (config.load_dotenv) would cut at ' #' or strip."""
    return f'"{value}"' if (" #" in value or value != value.strip() or value[:1] in "'\"") and '"' not in value else value


def write_env(key: str, value: str | None) -> None:
    p = env_path()
    lines = p.read_text(encoding="utf-8-sig").splitlines() if p.exists() else []
    out, done = [], False
    for line in lines:
        if re.match(rf"\s*(export\s+)?{re.escape(key)}\s*=", line):
            if value and not done:
                out.append(f"{key}={_quoted(value)}")
                done = True
            continue
        out.append(line)
    if value and not done:
        out.append(f"{key}={_quoted(value)}")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("\n".join(out).strip("\n") + "\n", encoding="utf-8")
    tmp.replace(p)


def state() -> dict[str, Any]:
    out = {}
    for k, (label, desc, check) in KEYS.items():
        v = os.environ.get(k) or ""
        out[k] = {"label": label, "desc": desc, "set": bool(v), "masked": mask(v), "problem": check(v) if v else None}
    return {"keys": out, "file": str(env_path())}


class KeyReq(BaseModel):
    key: str
    value: str = ""


@router.get("/keys")
async def keys_ep():
    return state()


@router.put("/keys")
async def put_key(req: KeyReq):
    if req.key not in KEYS:
        raise HTTPException(400, "unknown key")
    v = req.value.strip()
    if v:
        bad = KEYS[req.key][2](v)
        if bad:
            raise HTTPException(400, bad)
    write_env(req.key, v or None)
    if v:
        os.environ[req.key] = v
    else:
        os.environ.pop(req.key, None)
    return state()
