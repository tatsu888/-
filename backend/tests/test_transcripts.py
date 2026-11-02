from fastapi.testclient import TestClient

from app import transcripts as T

PREV = "当期の売上高は1,200億円となり、前年比5%の増収でした。半導体向けは堅調に推移しました。通期見通しは据え置きます。"
CUR = """当期の売上高は1,150億円となり、前年比▲4%の減収でした。中国向けの需要減が続き、在庫調整が長引いています。通期見通しを下方修正し、営業利益は300億円を計画します。

Q: 中国の受注はいつ回復しますか？
A: 現時点では見通せない状況で、コメントは差し控えさせていただきます。

質問：値上げは浸透していますか？
回答：はい、第2四半期に平均3%の値上げが浸透しました。"""


def test_tone_numbers_and_guidance():
    r = T.analyze(CUR, PREV)
    assert r["tone"]["negative"] > r["tone"]["positive"] and r["tone_change"] < 0
    nums = {(n["value"], n["unit"]) for n in r["numbers"]}
    assert (1150.0, "億円") in nums and (-4.0, "%") in nums and (300.0, "億円") in nums
    assert any(n["guidance"] and n["value"] == 300 for n in r["numbers"])
    assert r["diff"]["cosine"] < 0.9 and r["diff"]["new_count"] >= 1


def test_evasiveness():
    r = T.analyze(CUR)
    labels = [q["label"] for q in r["qa"]]
    assert labels == ["回避的", "直接的"]


def test_english_tone_and_diff_identical():
    t = "Revenue grew 12% to $3.4 billion. We expect strong momentum. Margins may face pressure."
    assert T.tone(t)["positive"] >= 2 and T.tone(t)["negative"] == 1
    d = T.diff(t, t)
    assert abs(d["cosine"] - 1) < 1e-9 and d["new_count"] == 0


def test_validate_brief():
    v = T.validate_brief(CUR, "## Bull\n- 値上げ3%が浸透 [S6]\n## Bear\n- 売上1,150億円 [S0]\n- 営業利益350億円 [S2]\n- 中国は弱い\n- 需要は戻る (推測)")
    oks = [l["ok"] for l in v["lines"]]
    assert oks == [True, True, False, False, True] and v["violations"] == 2
    assert "出典に無い数字" in v["lines"][2]["problems"][0]


def test_transcripts_api():
    from app.main import app

    with TestClient(app) as c:
        assert c.post("/api/transcripts/TSE:6501", json={"period": "2026Q1", "text": PREV}).json()["count"] == 1
        assert c.post("/api/transcripts/TSE:6501", json={"period": "2026Q2", "text": CUR}).json()["count"] == 2
        r = c.get("/api/transcripts/TSE:6501/analyze").json()
        assert r["period"] == "2026Q2" and r["prev_period"] == "2026Q1" and len(r["history"]) == 1
        p = c.get("/api/transcripts/TSE:6501/brief_pack").json()
        assert "[S0]" in p["prompt"]
        v = c.post("/api/transcripts/TSE:6501/validate_brief", json={"brief": "- 売上1,150億円 [S0]"}).json()
        assert v["ok"] is True
