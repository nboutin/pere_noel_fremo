import os
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

# Fuseau de référence du Défi du lutin et du Repas de Noël.
PARIS_TZ = ZoneInfo("Europe/Paris")
PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent


def resolve_res_dir() -> Path:
    env_dir = os.environ.get("FREMO_RES_DIR")
    if env_dir:
        return Path(env_dir)
    app_res = Path("/app/res")
    if app_res.exists():
        return app_res
    return PROJECT_ROOT / "res"


def resolve_logs_dir() -> Path:
    env_dir = os.environ.get("FREMO_LOGS_DIR")
    if env_dir:
        return Path(env_dir)
    app_logs = Path("/app/logs")
    if app_logs.exists():
        return app_logs
    return PROJECT_ROOT / "logs"


def default_db_path(res_dir: Path | str | None = None) -> Path:
    base = Path(res_dir) if res_dir is not None else resolve_res_dir()
    return base / "fremo.db"


def _read_secure_data_key(key: str, res_dir: Path | str | None = None) -> str | None:
    base = Path(res_dir) if res_dir is not None else resolve_res_dir()
    secure_data_path = base / "secure_data.yml"
    if not secure_data_path.exists():
        return None
    try:
        with open(secure_data_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            val = data.get(key)
            return str(val) if val is not None else None
    except Exception:
        return None


def get_admin_password(res_dir: Path | str | None = None) -> str | None:
    env_val = os.environ.get("ADMIN_PASSWORD")
    if env_val:
        return env_val
    return _read_secure_data_key("admin_password", res_dir=res_dir)


def get_base_url(res_dir: Path | str | None = None) -> str | None:
    """URL publique canonique des Liens magiques (clé `base_url` de `secure_data.yml`)."""
    return _read_secure_data_key("base_url", res_dir=res_dir)


def get_admin_session_secret(res_dir: Path | str | None = None) -> str | None:
    env_val = os.environ.get("ADMIN_SESSION_SECRET")
    if env_val:
        return env_val
    return _read_secure_data_key("admin_session_secret", res_dir=res_dir)
