"""Atomic KEY=VALUE env-file reader/writer.

Both /opt/hermes/.env (systemd EnvironmentFile) and $HERMES_HOME/.env (Hermes'
own provider-key store) are edited at runtime by the panel, so writes must be
atomic and must preserve comments + ordering.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_VALID_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_SENSITIVE_KEY_RE = re.compile(r"(?i)(_KEY|_TOKEN|_SECRET|_PASSWORD|_HASH)$")
_QUOTED_VALUE_RE = re.compile(r'^"(.*)"$|^\'(.*)\'$', re.DOTALL)


def _parse_value(raw: str) -> str:
    m = _QUOTED_VALUE_RE.match(raw)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2)
    return raw


def read_env(path: Path) -> dict[str, str]:
    """Parse an env file into a dict. Missing file → empty dict."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw_value = stripped.partition("=")
        key = key.strip()
        if key:
            result[key] = _parse_value(raw_value.strip())
    return result


def set_env(path: Path, key: str, value: str) -> None:
    """Set one key atomically, preserving every other line as-is."""
    if not _VALID_KEY_RE.match(key):
        raise ValueError(f"Invalid env key: {key!r}")
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []
    new_line = f"{key}={value}\n"
    out: list[str] = []
    found = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped or "=" not in stripped:
            out.append(line)
            continue
        if stripped.partition("=")[0].strip() == key:
            out.append(new_line)
            found = True
        else:
            out.append(line)
    if not found:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append(new_line)
    _atomic_write(path, "".join(out))


def delete_env(path: Path, key: str) -> bool:
    """Remove a key. Returns True when it was present."""
    if not _VALID_KEY_RE.match(key):
        raise ValueError(f"Invalid env key: {key!r}")
    if not path.exists():
        return False
    out: list[str] = []
    found = False
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            if stripped.partition("=")[0].strip() == key:
                found = True
                continue
        out.append(line)
    if found:
        _atomic_write(path, "".join(out))
    return found


def mask_value(key: str, value: str) -> str:
    """Mask secrets, keeping the last 4 chars for recognisability."""
    if _SENSITIVE_KEY_RE.search(key):
        return "****" if len(value) <= 4 else f"****{value[-4:]}"
    return value


def _atomic_write(path: Path, content: str) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".env_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
