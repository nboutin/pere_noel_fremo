import os
from pathlib import Path

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
