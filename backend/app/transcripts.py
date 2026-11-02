"""Earnings-call / briefing transcript analytics (TXT) — deterministic, no LLM.

Ideas commonly shared by people doing "AI analysis" on X, re-implemented so the numbers are
reproducible and every claim is traceable to a sentence:

* Lazy Prices diff  — Cohen, Malloy & Nguyen (2020): firms whose disclosure language changes a lot
  vs the previous period tend to underperform. We measure cosine / Jaccard similarity to the previous
  transcript and list the sentences that are new or were dropped.
* Tone              — small built-in EN/JA lexicons (positive / negative / uncertainty), Loughran-McDonald
  style counting. (Lexicons are short and editable — they are NOT the LM dictionary itself.)
* Q&A evasiveness   — per answer: hedging/non-answer phrases + low lexical overlap with the question.
* Numbers with citations — every number (%, 億円, bn …) with the sentence id it came from, flagged
  when it sits in a guidance sentence.
* Citation harness  — an AI-written bull/bear brief must cite [S#] for every sentence that contains a
  number, and the number must appear in the cited sentence; ``validate_brief`` checks this.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

POS = {"en": ["strong", "record", "growth", "improve", "improved", "improving", "exceed", "exceeded", "beat", "robust",
              "solid", "momentum", "accelerate", "accelerating", "upside", "raise", "raised", "gain", "gains", "favorable",
              "outperform", "expand", "expansion", "healthy", "confident", "best", "increase", "increased"],
       "ja": ["増収", "増益", "好調", "堅調", "過去最高", "最高益", "上方修正", "拡大", "改善", "回復", "伸長", "順調", "上振れ",
              "強い", "成長", "増加", "好転", "需要旺盛", "受注増", "値上げ浸透"]}
NEG = {"en": ["weak", "decline", "declined", "decrease", "decreased", "loss", "losses", "miss", "missed", "headwind",
              "headwinds", "pressure", "slowdown", "soft", "softness", "challenging", "difficult", "lower", "cut",
              "impairment", "downturn", "deteriorate", "deteriorated", "risk", "shortfall", "delay", "delayed"],
       "ja": ["減収", "減益", "低迷", "軟調", "悪化", "下方修正", "減少", "縮小", "下振れ", "逆風", "厳しい", "苦戦", "赤字",
              "減損", "停滞", "遅延", "在庫調整", "需要減", "鈍化", "弱含み"]}
UNC = {"en": ["may", "might", "could", "uncertain", "uncertainty", "approximately", "believe", "depends", "depending",
              "possibly", "perhaps", "unclear", "volatile", "visibility", "assume", "assumption", "roughly", "potential"],
       "ja": ["不透明", "見通せない", "可能性", "想定", "見込み", "程度", "かもしれ", "と思われ", "不確実", "様子見", "精査中",
              "検討中", "流動的", "現時点では"]}
NON_ANSWER = ["we don't disclose", "we do not disclose", "not going to comment", "no comment", "too early to say",
              "too early to tell", "we'll provide more", "we will provide more", "can't comment", "cannot comment",
              "コメントは差し控え", "差し控えさせて", "開示していない", "お答えできない", "回答を控え", "現時点では申し上げられ",
              "改めてお知らせ", "精査中", "検討中"]
GUIDANCE = ["guidance", "outlook", "forecast", "expect", "target", "plan", "full-year", "full year", "next quarter",
            "見通し", "予想", "計画", "目標", "ガイダンス", "通期", "来期", "中期経営計画", "会社計画"]

_NUM = re.compile(r"(?P<sign>[▲△\-−+])?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
                  r"(?P<unit>%|％|bp|bps|億円|百万円|千円|兆円|万円|円|億ドル|ドル|倍|x|bn|billion|million|mn|m\b|pt|ポイント)?",
                  re.IGNORECASE)
_CJK = re.compile(r"[぀-ヿ㐀-鿿]+")
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]+")


def sentences(text: str) -> list[str]:
    text = re.sub(r"\r\n?", "\n", text or "")
    parts = re.split(r"(?<=[。！？!?])\s*|(?<=\.)\s+(?=[A-Z\"'(])|\n{2,}|\n(?=(?:Q|A|質問|回答)\s*[:：])", text)
    return [p.strip() for p in parts if p and p.strip()]


def tokens(s: str) -> list[str]:
    out = [w.lower() for w in _WORD.findall(s)]
    for run in _CJK.findall(s):
        out += [run[i:i + 2] for i in range(len(run) - 1)] if len(run) > 1 else [run]
    return out


def _count(text_l: str, words: list[str], en: bool) -> int:
    if en:
        return sum(len(re.findall(rf"\b{re.escape(w)}\b", text_l)) for w in words)
    return sum(text_l.count(w) for w in words)


def tone(text: str) -> dict[str, Any]:
    t = (text or "").lower()
    pos = _count(t, POS["en"], True) + _count(t, POS["ja"], False)
    neg = _count(t, NEG["en"], True) + _count(t, NEG["ja"], False)
    unc = _count(t, UNC["en"], True) + _count(t, UNC["ja"], False)
    n = max(len(tokens(text)), 1)
    return {"positive": pos, "negative": neg, "uncertainty": unc, "tokens": n,
            "net_tone": (pos - neg) / (pos + neg) if pos + neg else 0.0,
            "uncertainty_per_1k": unc / n * 1000}


def cosine(a: Counter, b: Counter) -> float:
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _sim(a: str, b: str) -> float:
    return cosine(Counter(tokens(a)), Counter(tokens(b)))


def diff(prev: str, cur: str, threshold: float = 0.6, limit: int = 40) -> dict[str, Any]:
    """Lazy-prices style change: overall similarity + sentences that are new / dropped."""
    ps, cs = sentences(prev), sentences(cur)
    cos = cosine(Counter(tokens(prev)), Counter(tokens(cur)))
    sa, sb = set(tokens(prev)), set(tokens(cur))
    jac = len(sa & sb) / len(sa | sb) if sa | sb else 1.0
    pvec = [Counter(tokens(s)) for s in ps]
    cvec = [Counter(tokens(s)) for s in cs]
    new = []
    for i, v in enumerate(cvec):
        best = max((cosine(v, p) for p in pvec), default=0.0)
        if best < threshold:
            new.append({"sid": i, "text": cs[i], "best_match": best, "tone": tone(cs[i])["net_tone"]})
    dropped = []
    for i, v in enumerate(pvec):
        best = max((cosine(v, c) for c in cvec), default=0.0)
        if best < threshold:
            dropped.append({"sid": i, "text": ps[i], "best_match": best})
    return {"cosine": cos, "jaccard": jac, "change_score": 1 - cos, "new_sentences": new[:limit],
            "dropped_sentences": dropped[:limit], "new_count": len(new), "dropped_count": len(dropped),
            "sentences_prev": len(ps), "sentences_cur": len(cs),
            "note": "Lazy Prices: 前回からの言語変化が大きい（類似度が低い）ほど、その後アンダーパフォームしやすいという実証研究。"
                    "絶対水準より同社の過去の変化幅との比較で見る。"}


def numbers(text: str) -> list[dict[str, Any]]:
    out = []
    for sid, s in enumerate(sentences(text)):
        g = any(k in s.lower() for k in GUIDANCE)
        for m in _NUM.finditer(s):
            unit = m.group("unit")
            raw = m.group("num")
            if not unit and len(raw) == 4 and raw.startswith(("19", "20")):
                continue  # a year, not a figure
            if not unit and "," not in raw and "." not in raw and float(raw) < 10:
                continue  # bare small integers (list markers, "Q1")
            val = float(raw.replace(",", ""))
            if m.group("sign") in ("▲", "△", "-", "−"):
                val = -val
            out.append({"sid": sid, "value": val, "unit": unit or "", "raw": m.group(0).strip(), "guidance": g,
                        "context": s[:200]})
    return out


def qa_pairs(text: str) -> list[dict[str, Any]]:
    """Split 'Q: … A: …' / '質問：… 回答：…' blocks."""
    blocks = re.split(r"\n?\s*(Q|A|質問|回答)\s*[:：]\s*", text or "")
    pairs, q = [], None
    for i in range(1, len(blocks) - 1, 2):
        tag, body = blocks[i], blocks[i + 1].strip()
        if tag in ("Q", "質問"):
            q = body
        elif q is not None:
            pairs.append({"q": q, "a": body})
            q = None
    return pairs


def evasiveness(q: str, a: str) -> dict[str, Any]:
    al = a.lower()
    non = [p for p in NON_ANSWER if p in al]
    t = tone(a)
    overlap = _sim(q, a)
    nums = len(numbers(a))
    score = min(1.0, 0.45 * min(len(non), 2) / 2 + 0.25 * min(t["uncertainty_per_1k"] / 40, 1)
                + 0.2 * (1 - min(overlap / 0.3, 1)) + 0.1 * (1 if nums == 0 else 0))
    return {"score": score, "non_answer_phrases": non, "overlap_with_question": overlap,
            "uncertainty_per_1k": t["uncertainty_per_1k"], "numbers_in_answer": nums,
            "label": "回避的" if score >= 0.6 else "やや回避的" if score >= 0.4 else "直接的"}


def analyze(cur: str, prev: str | None = None) -> dict[str, Any]:
    ss = sentences(cur)
    res: dict[str, Any] = {"sentences": [{"sid": i, "text": s} for i, s in enumerate(ss)], "tone": tone(cur),
                           "numbers": numbers(cur)}
    pairs = qa_pairs(cur)
    res["qa"] = [{"q": p["q"][:400], "a": p["a"][:600], **evasiveness(p["q"], p["a"])} for p in pairs]
    if res["qa"]:
        res["evasiveness_avg"] = sum(x["score"] for x in res["qa"]) / len(res["qa"])
    if prev:
        res["diff"] = diff(prev, cur)
        pt = tone(prev)
        res["tone_prev"] = pt
        res["tone_change"] = res["tone"]["net_tone"] - pt["net_tone"]
        res["uncertainty_change"] = res["tone"]["uncertainty_per_1k"] - pt["uncertainty_per_1k"]
    # sentence-level tone extremes (cited)
    scored = [(i, tone(s)["net_tone"], s) for i, s in enumerate(ss) if tone(s)["positive"] + tone(s)["negative"]]
    res["most_positive"] = [{"sid": i, "tone": t, "text": s} for i, t, s in sorted(scored, key=lambda x: -x[1])[:5] if t > 0]
    res["most_negative"] = [{"sid": i, "tone": t, "text": s} for i, t, s in sorted(scored, key=lambda x: x[1])[:5] if t < 0]
    return res


# ---------------------------------------------------------------------------
# Citation harness for AI-written bull / bear briefs
# ---------------------------------------------------------------------------
BRIEF_RULES = """あなたは提示された SOURCE 文（[S0] [S1] …）だけを根拠に Bull case と Bear case を書く。
規則:
1. 数字を含む文は必ず末尾に出典 [S#] を付ける。数字は出典の文に実在するものだけを使う（計算値は不可。必要なら「出典では…」と原文の数字を引用）。
2. SOURCE にない事実・推測は書かない。推測が必要なら「(推測)」と明記し、数字を含めない。
3. Bull 3点・Bear 3点。各点は1〜2文。最後に「コンセンサスが依拠する最も脆弱な前提」を1文（出典付き）。
4. 出力形式:
## Bull
- … [S#]
## Bear
- … [S#]
## 脆弱な前提
- … [S#]"""


def brief_pack(text: str, symbol: str = "", max_sentences: int = 400) -> dict[str, Any]:
    ss = sentences(text)[:max_sentences]
    src = "\n".join(f"[S{i}] {s}" for i, s in enumerate(ss))
    prompt = f"{BRIEF_RULES}\n\n銘柄: {symbol}\n\nSOURCE:\n{src}\n"
    return {"prompt": prompt, "sentences": len(ss)}


def _norm_num(s: str) -> list[float]:
    out = []
    for m in _NUM.finditer(s):
        try:
            out.append(float(m.group("num").replace(",", "")))
        except ValueError:
            pass
    return out


def validate_brief(source_text: str, brief: str) -> dict[str, Any]:
    """Every brief line with a number must cite [S#] and each number must appear in a cited sentence."""
    ss = sentences(source_text)
    lines = [ln.strip(" -•\t") for ln in (brief or "").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    rows, bad = [], 0
    for ln in lines:
        cites = [int(c) for c in re.findall(r"\[S(\d+)\]", ln)]
        body = re.sub(r"\[S\d+\]", "", ln)
        nums = [n for n in _norm_num(body) if not (1900 <= n <= 2100 and float(n).is_integer())]
        problems = []
        invalid = [c for c in cites if c >= len(ss)]
        if invalid:
            problems.append(f"存在しない出典 {invalid}")
        if nums and not cites:
            problems.append("数字があるのに出典がない")
        if nums and cites:
            pool = [n for c in cites if c < len(ss) for n in _norm_num(ss[c])]
            missing = [n for n in nums if not any(abs(n - p) < 1e-9 for p in pool)]
            if missing:
                problems.append(f"出典に無い数字 {missing}")
        speculative = "(推測)" in ln or "（推測）" in ln
        if not cites and not speculative:
            problems.append("出典も(推測)表記もない")
        bad += bool(problems)
        rows.append({"line": ln, "cites": cites, "numbers": nums, "ok": not problems, "problems": problems})
    return {"lines": rows, "ok": bad == 0, "violations": bad, "checked": len(rows)}
