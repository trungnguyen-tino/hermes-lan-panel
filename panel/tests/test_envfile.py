from __future__ import annotations

import pytest

from hermes_panel.envfile import delete_env, mask_value, read_env, set_env


def test_read_env_ignores_comments_and_blank_lines(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# note\n\nA=1\nB = 2 \nbroken\n", encoding="utf-8")
    assert read_env(path) == {"A": "1", "B": "2"}


def test_read_env_strips_quotes(tmp_path):
    path = tmp_path / ".env"
    path.write_text('A="giá trị"\nB=\'x\'\n', encoding="utf-8")
    assert read_env(path) == {"A": "giá trị", "B": "x"}


def test_set_env_updates_in_place_and_keeps_comments(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# đầu file\nA=1\nB=2\n", encoding="utf-8")
    set_env(path, "A", "9")
    assert path.read_text(encoding="utf-8") == "# đầu file\nA=9\nB=2\n"


def test_set_env_appends_missing_key(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1", encoding="utf-8")  # không có newline cuối
    set_env(path, "B", "2")
    assert read_env(path) == {"A": "1", "B": "2"}


def test_set_env_creates_file_with_restrictive_mode(tmp_path):
    path = tmp_path / "sub" / ".env"
    set_env(path, "TOKEN", "abc")
    assert read_env(path) == {"TOKEN": "abc"}
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_set_env_rejects_invalid_key(tmp_path):
    with pytest.raises(ValueError):
        set_env(tmp_path / ".env", "bad key", "x")


def test_delete_env(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1\nB=2\n", encoding="utf-8")
    assert delete_env(path, "A") is True
    assert delete_env(path, "A") is False
    assert read_env(path) == {"B": "2"}


def test_mask_value_only_masks_secrets():
    assert mask_value("OPENAI_API_KEY", "sk-abcdefgh") == "****efgh"
    assert mask_value("SHORT_TOKEN", "ab") == "****"
    assert mask_value("HERMES_HOME", "/root/.hermes") == "/root/.hermes"
