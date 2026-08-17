"""Panel settings — resolved from /opt/hermes/.env + process environment.

systemd injects the same file via EnvironmentFile=, but we re-read it on every
Settings build so values edited by the panel itself (owner uid, API keys) are
visible without restarting the service.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from hermes_panel.envfile import read_env

DEFAULT_ENV_FILE = "/opt/hermes/.env"

# systemctl actions are only ever run against this allowlist.
ALLOWED_SERVICES = ("hermes-gateway", "hermes-dashboard", "hermes-panel", "hermes.target")


@dataclass(frozen=True)
class Settings:
    env_file: Path
    hermes_home: Path
    hermes_bin: Path
    zalo_plugin_dir: Path
    panel_port: int
    dashboard_port: int
    chat_url: str
    admin_user: str
    password_hash: str
    session_secret: str
    session_ttl: int = 7 * 86400

    @property
    def hermes_env_file(self) -> Path:
        """Hermes' own .env — where provider API keys must also land."""
        return self.hermes_home / ".env"

    def merged_env(self) -> dict[str, str]:
        """Both env stores merged; Hermes' own store wins on conflict."""
        merged = read_env(self.env_file)
        merged.update(read_env(self.hermes_env_file))
        return merged


def _value(env: dict[str, str], key: str, default: str = "") -> str:
    """Process env wins (systemd injected it), then the file, then default."""
    return os.environ.get(key) or env.get(key, "") or default


def build_settings(env_file: str | None = None) -> Settings:
    path = Path(env_file or os.environ.get("HERMES_PANEL_ENV_FILE") or DEFAULT_ENV_FILE)
    env = read_env(path)
    hermes_home = Path(_value(env, "HERMES_HOME", "/root/.hermes"))
    try:
        panel_port = int(_value(env, "HERMES_PANEL_PORT", "8088"))
    except ValueError:
        panel_port = 8088
    try:
        dashboard_port = int(_value(env, "HERMES_DASHBOARD_PORT", "9119"))
    except ValueError:
        dashboard_port = 9119
    return Settings(
        env_file=path,
        hermes_home=hermes_home,
        hermes_bin=Path(_value(env, "HERMES_BIN", "/usr/local/bin/hermes")),
        zalo_plugin_dir=hermes_home / "plugins" / "zalo-personal",
        panel_port=panel_port,
        dashboard_port=dashboard_port,
        chat_url=_value(env, "HERMES_CHAT_URL"),
        admin_user=_value(env, "HERMES_PANEL_USER", "admin"),
        password_hash=_value(env, "HERMES_PANEL_PASSWORD_HASH"),
        session_secret=_value(env, "HERMES_PANEL_SESSION_SECRET"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return build_settings()
