import os

from app.config import load_dotenv


def test_load_dotenv_does_not_override(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# c\nFOO_A=1  # note\nFOO_B='x y'\nexport FOO_C=3\nFOO_D=keep\n", encoding="utf-8")
    monkeypatch.delenv("TERMINAL_NO_DOTENV", raising=False)
    monkeypatch.setenv("FOO_D", "env")
    for k in ("FOO_A", "FOO_B", "FOO_C"):
        monkeypatch.delenv(k, raising=False)
    loaded = load_dotenv(f)
    assert os.environ["FOO_A"] == "1" and os.environ["FOO_B"] == "x y" and os.environ["FOO_C"] == "3"
    assert os.environ["FOO_D"] == "env" and "FOO_D" not in loaded
    for k in ("FOO_A", "FOO_B", "FOO_C"):
        monkeypatch.delenv(k, raising=False)
