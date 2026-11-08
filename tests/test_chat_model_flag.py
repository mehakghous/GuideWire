"""`chat --model-tier` reads the key it is told to and refuses cleanly when it is missing; without the flag chat stays offline."""
from ingestion import cli


def test_chat_model_tier_without_its_key_says_which_variable_to_set(monkeypatch, tmp_path, capsys):
    script = tmp_path / "q.txt"
    script.write_text("how do i join 2 objects\n", encoding="utf-8")
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("GEMINI_API_KEY_TEST", raising=False)
    assert cli.main(["chat", "--model-tier", "iterate", "--key", "test", "--script", str(script)]) == 2
    assert "GEMINI_API_KEY_TEST" in capsys.readouterr().err


def test_chat_without_the_flag_is_offline_and_needs_no_key(monkeypatch, tmp_path, capsys):
    script = tmp_path / "q.txt"
    script.write_text("how do i join 2 objects\n", encoding="utf-8")
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    for k in ("GEMINI_API_KEY", "GEMINI_API_KEY_DEV", "GEMINI_API_KEY_TEST"):
        monkeypatch.delenv(k, raising=False)
    assert cli.main(["chat", "--no-kb", "--script", str(script)]) == 0
    assert "join" in capsys.readouterr().out.lower()
