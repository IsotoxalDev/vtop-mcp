import os
import tomllib
from pathlib import Path

_data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
DATA_DIR = _data_home / "vtop-mcp"
PROFILE_DIR = DATA_DIR / "browser-profile"

DATA_DIR.mkdir(parents=True, exist_ok=True)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = Path(os.environ.get("VTOP_CONFIG_PATH", _PROJECT_ROOT / "config.toml"))


def _load_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


_file_config = _load_toml(_CONFIG_PATH)


def _get(key: str, env_var: str, default: str | None = None) -> str | None:
    return os.environ.get(env_var) or _file_config.get(key) or default


VTOP_BASE_URL = (_get("base_url", "VTOP_BASE_URL", "https://vtopcc.vit.ac.in/vtop") or "").rstrip("/")
VTOP_USERNAME = _get("username", "VTOP_USERNAME")
VTOP_PASSWORD = _get("password", "VTOP_PASSWORD")

LOGIN_TIMEOUT_S = int(_get("login_timeout_s", "VTOP_LOGIN_TIMEOUT_S", "300"))
NAV_TIMEOUT_MS = int(_get("nav_timeout_ms", "VTOP_NAV_TIMEOUT_MS", "30000"))

# Reuse an already-installed Chromium instead of Playwright's own pinned copy
# (which drags in a large extra dependency closure). Set by the flake's shellHook
# when it finds one on PATH; leave unset to let Playwright manage its own browser.
CHROMIUM_PATH = os.environ.get("VTOP_MCP_CHROMIUM_PATH") or None
