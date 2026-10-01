# VISION · Full build (Phases 1–7)

Your personal assistant's backbone: the orchestrator, 10 masters with one reporter each,
live dashboard, boot roll call, schedules, and auto-start on the Mac mini.

## What works now
- **Dashboard** at http://127.0.0.1:8765, the same design as the canvas, now fed live by the core
  (top bar reads `LIVE · CORE CONNECTED`).
- **Boot roll call** is real: every master runs its first cycle on start or restart, sub-agents
  pass work down their chain, only the reporter reports to the master, the master reports to VISION.
- **Traffic Desk is live** (TomTom). Every other master runs as a *stub* (demo statuses) until we build it.
- **Errors** turn the agent red, block the rest of its chain, and alert the master in the log.
- **Schedules**: each master refreshes every 15 min (Traffic every 10); briefs compile at 6:00 AM and 6:00 PM.
- **History** in `data/vision.db` (SQLite): every agent run, every master report.

## Telegram (Phase 2), whenever you're ready
VISION runs fine without it; the dashboard timeline shows `TELEGRAM off · add TELEGRAM_BOT_TOKEN`.
1. In Telegram, message **@BotFather** → `/newbot` → pick a name → copy the **token**.
2. Put it in `.env` as `TELEGRAM_BOT_TOKEN=...` and restart VISION.
3. Open your new bot, send **/start**: it replies with **your chat ID**.
4. Put that in `.env` as `TELEGRAM_CHAT_ID=...` and restart. Done.

What you get: ☀️ 6:00 AM and 🌙 6:00 PM briefs (master reports only), instant alerts when an agent fails
(same error at most once per 30 min), approvals with ✅ Approve / ✖ Reject buttons, and commands:
`/brief` `/status` `/traffic Windsor` `/approvals` `/help`, or just type *what's up*.
The bot answers only your chat ID and ignores everyone else. No open ports: it uses long polling.
Turn off instant alerts with `telegram: alerts: false` in config.yaml.

## News Desk + Weather (Phase 3): nothing to set up
Live by default. Headlines come from Google News RSS searches (many outlets per topic) for
India markets, global markets, cricket and politics; weather and a 16-day forecast come from
Open-Meteo for your home city. The forecast also drives the Calendar tiles' weather icons.
Change the searches or add publisher RSS feeds in `config.yaml → masters.news.options`.

## Investments (Phase 4): read-only, set up any time, in any order
Any broker not set up yet simply shows *NOT SET UP* or *LOGIN*; the others still report.
- **Zerodha (Kite MCP, free):** nothing to configure. When a login is needed, VISION shows a
  **Log in** button on the dashboard and sends the link on Telegram. Log in to Kite once a day.
- **Fyers:** create an app at myapi.fyers.in with Redirect URL `http://127.0.0.1:8765/auth/fyers/callback`,
  put `FYERS_APP_ID` and `FYERS_SECRET` in `.env`, restart, then tap **Log in** when asked.
  Optional `FYERS_PIN` lets VISION renew the daily token itself for ~15 days.
- **Wealthsimple:** Documents → custom statement → Holdings report → CSV. Drop it into
  `inbox/wealthsimple/`. Prices refresh live between exports; VISION reminds you after 7 days.
- Optional: `COINGECKO_API_KEY` (free Demo key), and allocation `targets` in `config.yaml`.
The brief shows yesterday's P&L per account and in CAD, NIFTY / BANK NIFTY / NIFTY IT, NYSE,
NASDAQ and Bitcoin. Nothing in this master can trade.

## Email + Calendar (Phase 5)
List your inboxes in `config.yaml → masters.email.options.accounts` (and calendar), e.g.
`- { id: personal, provider: google }`. Then create a sign-in app once:
- **Google:** console.cloud.google.com → new project → enable *Gmail API* and *Google Calendar API* →
  OAuth consent screen (External, add yourself as a test user) → Credentials → OAuth client ID →
  *Web application*, redirect URI `http://127.0.0.1:8765/auth/google/callback` →
  `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `.env`.
- **Microsoft (Outlook/Hotmail):** entra.microsoft.com → App registrations → New (personal + work accounts) →
  Web redirect `http://127.0.0.1:8765/auth/microsoft/callback` → new client secret →
  `MS_CLIENT_ID` / `MS_CLIENT_SECRET`.
Restart, then tap **Log in** in the dashboard's approvals panel once per account.
What happens: the last 24 h of every inbox (read or not) is sorted; what needs you is flagged; replies
are drafted in your tone and **sent only after you approve**. Meeting requests become proposed slots on
your calendar; approving books the event (invites go out) and replies. Reminders arrive on Telegram.

## Ask engine + voice (Phase 6)
- **LM Studio:** load a 7–8B instruct model that supports tool use, start the server
  (Developer tab), and put its model id in `config.yaml → llm.local_model`. VISION now answers any
  phrasing, remembers the conversation for 30 minutes, and calls the right masters itself.
  Optional: `ANTHROPIC_API_KEY` + `llm.cloud_model` for the deep-reasoning agents.
  No model running? The dashboard's built-in engine answers instead.
- **Local voice (optional):** `.venv/bin/pip install -r requirements-voice.txt` and `brew install ffmpeg`.
  - Speech: set `voice.tts: kokoro` and put `kokoro-v1.0.onnx` + `voices-v1.0.bin` (from the
    kokoro-onnx project's releases) in `models/`. The rings then follow the real audio loudness.
    Or `voice.tts: macos` (uses Serena; add it in System Settings → Accessibility → Spoken Content).
  - Listening: `voice.stt: whisper` (runs on the M1, no audio leaves the Mac).
  - Wake word: `voice.wake: true`. The built-in model answers to "Hey Jarvis"; train your own
    "Hey Viz" model with openWakeWord's training notebook and point `voice.wake_model` at it.
- Approving by voice only works when your own words say so ("yes, send it").

## Phase 7 masters
| Master | Keys (`.env`) | Notes |
|---|---|---|
| **World Watch** | optional `OPENSKY_CLIENT_ID/SECRET` | Live flights on the globe; routes from adsbdb; refreshes every 5 min. |
| **Job Hunt** | `ADZUNA_APP_ID/KEY` (free) | Plus Job Bank alert emails and `target_companies` career pages. Put your resume at `vault/resume/master.md`. Packages land in `data/applications/`; **you** submit. |
| **Web Designer** | `GOOGLE_MAPS_API_KEY`, `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | Finds no-website businesses, builds and deploys a demo to workers.dev, drafts the pitch for your OK. Four page styles, ColorHunt palettes, stock photos from Pexels/Pixabay (optional `PEXELS_API_KEY`, `PIXABAY_API_KEY`) or Openverse, saved locally with credits on the page. |
| **Trading Desk** | `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`, `OANDA_ENV=practice` | Analysts → debate → judge → risk → your OK → order. Practice only until `live_trading: true` *and* `OANDA_ENV=live`. Approvals expire after 30 min and are refused if price moved too far. |

## Setup (once)
```bash
# put this folder at ~/VISION, then:
cd ~/VISION
bash scripts/setup.sh              # venv, dependencies, creates .env, runs a check
open -e .env                       # add TOMTOM_API_KEY (free at developer.tomtom.com)
.venv/bin/python -m vision         # start; open http://127.0.0.1:8765
```
Auto-start at login + restart on crash:
```bash
bash scripts/install_launchagent.sh
```
Also on the Mac: System Settings → Energy → prevent automatic sleep, and start up after power failure.

## The two files you edit
| File | What goes in it |
|---|---|
| `.env` | Secrets only: API keys, tokens. Never share it. |
| `config.yaml` | Everything else: home city, brief times, which masters are on, `mode: stub/live`, trust, traffic cities. |

## Handy commands
```bash
.venv/bin/python -m vision check              # config + which keys are set
.venv/bin/python -m vision traffic "Windsor"  # test TomTom directly
.venv/bin/python -m pytest -q                 # run the tests
tail -f logs/vision.log                       # watch it work
```
API: `GET /api/state` · `POST /api/boot` (re-run roll call) · `POST /api/masters/<id>/run` · `GET /api/brief` · `POST /api/brief/send` · `GET /api/traffic?city=`
· approvals: `GET /api/approvals` · `POST /api/approvals` · `POST /api/approvals/<id>/approved|rejected`

## How a master is built (for the next phases)
1. Write `vision/masters/<id>.py` with real `SubAgent` classes and a `build_agents(options)` function.
2. Register it in `LIVE_MODULES` in `vision/masters/__init__.py`.
3. Set `mode: live` for it in `config.yaml`. Any agent not built yet keeps running as a stub.

## Layout
```
vision/            core: config, bus + store, agents, orchestrator, server
vision/masters/    catalog.json (shared with the dashboard) + one module per live master
vision/services/   traffic_api.py, news.py, weather.py, markets.py, fyers.py, kite_mcp.py, wealthsimple.py
vision/channels/   telegram.py (briefs, alerts, reminders, commands, approval buttons)
vision/ask.py      AI Ask engine (tool calling into every master)
vision/voice/      local speech (Kokoro/Piper/macOS), Whisper listening, wake word
dashboard/         index.html, dc-runtime.js, Main.dc.html (the design), vendor/preact
launchd/ scripts/  auto-start
data/ logs/ vault/ inbox/   created on setup (not shared)
```

## Tested vs. untested
27 automated tests cover the core, every live master, approvals, Telegram, the Ask engine and voice fallbacks (see `tests/`). Every external service is mocked in tests. Real-world checks happen
on your Mac mini: run `.venv/bin/python -m vision check` after adding each key, and watch `logs/vision.log`.

## Credits
- Dashboard music (`dashboard/audio/`): "Inspired" by NEFFEX (boot roll call) and "Roadside (Azaleh VIP)" by Azaleh x Descant (ambient loop).
- Dashboard body font: "Pixelywave Tech Future" (freeware, non-commercial; https://www.fontspace.com/pixelywave-tech-future-font-f166250). Not in the repo: download it and save it as `dashboard/fonts/pixelywave.otf`; without it the dashboard falls back to a system font.
