"""Run the service: python -m tablo [--config config.yaml]."""

import argparse
import logging
import os
from pathlib import Path

from aiohttp import web

from . import config
from .app import create_app


def load_env(path: Path) -> None:
    """KEY=VALUE lines from .env (secrets, §6.5); real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def main() -> None:
    parser = argparse.ArgumentParser(prog="tablo")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--data", type=Path, default=Path("data"), help="directory for saved state")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    load_env(Path(".env"))

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # The config last pushed by Home Assistant wins over the file (§6.5).
    saved = args.data / "config.yaml"
    cfg = config.load(saved if saved.exists() else args.config)
    app = create_app(cfg, data_dir=args.data)
    web.run_app(app, host=cfg.host, port=cfg.port, access_log=None)


if __name__ == "__main__":
    main()
