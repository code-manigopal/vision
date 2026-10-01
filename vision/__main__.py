"""Run VISION:  python -m vision            (starts the server + boot roll call)
Quick checks:   python -m vision check      (validates config and keys, no server)
                python -m vision traffic "Toronto"
"""

import asyncio
import json
import logging
import sys
from logging.handlers import RotatingFileHandler

from .config import ROOT, load_config, secret


def _logging() -> None:
    (ROOT / "logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(ROOT / "logs" / "vision.log", maxBytes=2_000_000, backupCount=3)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[fh, sh])
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def check() -> int:
    cfg = load_config()
    print(f"config.yaml OK · home {cfg.vision.home_city} · briefs {', '.join(cfg.vision.brief_times)}")
    from .masters import build_masters
    for m in build_masters(cfg):
        print(f"  {m.name:<18} {'on ' if m.enabled else 'off'}  mode={m.mode:<4}  trust={m.trust:<8} reporter={m.reporter}")
    keys = {"TOMTOM_API_KEY": "Traffic Desk", "TELEGRAM_BOT_TOKEN": "Telegram bot", "TELEGRAM_CHAT_ID": "Telegram: your chat (send /start to the bot to get it)",
            "FYERS_APP_ID": "Investments · Fyers", "GOOGLE_CLIENT_ID": "Email + Calendar · Google sign-in", "MS_CLIENT_ID": "Email + Calendar · Microsoft sign-in",
            "ANTHROPIC_API_KEY": "Cloud model (optional)", "ADZUNA_APP_ID": "Job Hunt · Adzuna", "GOOGLE_MAPS_API_KEY": "Web Designer · Places",
            "CLOUDFLARE_API_TOKEN": "Web Designer · deploys", "OPENSKY_CLIENT_ID": "World Watch (optional)", "OANDA_API_TOKEN": "Trading Desk"}
    for k, used in keys.items():
        print(f"  {'✓' if secret(k) else '·'} {k:<22} {used}")
    import asyncio as _a
    from .services.llm import LLM
    llm = LLM(cfg)
    print(f"  {'✓' if _a.run(llm.local_available()) else '·'} LM Studio at {cfg.llm.local_base_url}" + ("" if cfg.llm.local_model else "  (set llm.local_model)"))
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["check"]:
        return check()
    if args[:1] == ["traffic"]:
        from .services.traffic_api import TrafficError, get_city_traffic
        load_config()
        try:
            print(json.dumps(asyncio.run(get_city_traffic(" ".join(args[1:]) or "Leamington")), indent=2))
            return 0
        except TrafficError as e:
            print(f"[{e.status}] {e}", file=sys.stderr)
            return 1
    _logging()
    import uvicorn
    from .server import create_app
    cfg = load_config()
    uvicorn.run(create_app(), host=cfg.vision.host, port=cfg.vision.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
