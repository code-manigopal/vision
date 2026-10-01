# VISION — handover for Claude Code

## Working rules (read first)
The goal is the best result for the fewest usage credits and tokens.
1. Delegate large, parallel, or search-heavy work to sub-agents (broad codebase sweeps, independent
   multi-file changes, long research). Do small, targeted edits directly — a sub-agent starts cold and
   re-reads context, so it costs more than it saves on a small task.
2. Give sub-agents the lightest model that can do the job: Haiku for simple lookups, searches, and
   mechanical edits; Sonnet for routine coding; the main model only for design and hard debugging.
3. Keep context lean: read only the parts of files you need, give sub-agents a self-contained brief,
   and ask them to return conclusions, not file dumps.

VISION is Mani's personal assistant: one always-on Python service on a **Mac mini M1 (16 GB)** that runs
**10 master agents**, each with its own sub-agents, a red/gold HUD dashboard, Telegram briefs/alerts,
an AI "Ask" engine (LM Studio local model + optional cloud), and optional local voice.
Phases 1–7 are built and unit-tested with mocked services. **No real external API has been exercised yet**;
first real runs happen on Mani's Mac.

## Working with Mani
- Direct and terse. Explain the plan briefly **before** building anything non-trivial; wait for a yes on design changes.
- Surgical, targeted fixes. No unnecessary rewrites or reformatting.
- Plain-language explanations for non-dev topics (he's a strong engineer: Java/C#, K8s, CI/CD).
- Backend is **Python only** (he chose this explicitly). Browser code stays JS.
- He reverts visual experiments he doesn't like — keep changes small and reversible.
- Never commit or print secrets. `.env` is his; only `.env.example` lives in the repo.

## Commands
```bash
bash scripts/setup.sh                     # venv + deps + .env from template + check
.venv/bin/python -m vision                # run (dashboard http://127.0.0.1:8765)
.venv/bin/python -m vision check          # config, which keys are set, LM Studio reachable
.venv/bin/python -m vision traffic "Windsor"
.venv/bin/python -m pytest -q             # 27 tests, all external services mocked
bash scripts/install_launchagent.sh       # auto-start at login + restart on crash
tail -f logs/vision.log
```
Optional voice extras: `.venv/bin/pip install -r requirements-voice.txt` + `brew install ffmpeg`.

## Architecture
```
vision/
  config.py        config.yaml (settings) + .env (secrets) -> Config; secret(name)
  bus.py           EventBus (live state + WebSocket fan-out) and Store (SQLite: agent_runs,
                   master_reports, approvals, kv JSON store used by masters)
  agents.py        SubAgent / StubAgent / Stage / Master; request_approval(ctx, ...)
  orchestrator.py  boot roll call, per-master schedules, 06:00/18:00 briefs, reminders (minutely),
                   approval actions (watches approval_decided -> APPROVAL_HANDLERS[kind])
  server.py        FastAPI: dashboard, /ws, /api/*, OAuth + Fyers login callbacks
  ask.py           AskEngine: LLM tool-calling over master data; session memory 30 min
  voice/           TTS (kokoro | piper | macos), STT (mlx-whisper), WakeWord (openWakeWord)
  channels/telegram.py   briefs, alerts, reminders, notices, /commands, approve/reject buttons
  services/        llm.py (LM Studio OpenAI-compatible + Anthropic), oauth.py (Google/Microsoft),
                   mailcal.py (Gmail/GCal/Graph), traffic_api.py (TomTom), news.py (Google News RSS),
                   weather.py (Open-Meteo), markets.py (Yahoo chart, CoinGecko, Bank of Canada FX),
                   fyers.py, kite_mcp.py (Zerodha via hosted Kite MCP, persistent session), wealthsimple.py (CSV),
                   sysmon.py (Instruments: CPU/memory via psutil, GPU via ioreg or nvidia-smi)
  masters/         catalog.json (shared with the dashboard) + one module per live master
dashboard/
  Main.dc.html     the HUD (canvas "design" format: {{holes}}, <sc-for>, <sc-if>, logic class)
  dc-runtime.js    renders Main.dc.html locally with vendored Preact (no build step)
  index.html       shell; scales the 1440x900 artboard to the window
  traffic-map.js   Google Maps dark style + traffic polylines (not wired into the HUD yet)
tests/             test_core, test_telegram, test_phase34, test_phase567
```

### Core rules (enforced in code — keep them)
1. **One reporter per master.** Sub-agents pass work down their chain (`ctx`); only the reporter's
   `AgentResult.summary` (+ `data`) becomes the master report. Briefs use master reports only.
   Reporters: email=Summarizer, calendar=Scheduler, trading=Portfolio Manager, invest=Daily P&L Reporter,
   news=News Summarizer, web=Proposal Drafter, jobs=Application Tracker, world=Flight Tracker,
   traffic=Incident Scout, film=Analytics Monitor.
2. **Errors skip the chain**: a failing agent turns red, alerts the master log (Telegram once/30 min),
   and blocks later stages — unless the agent sets `blocking = False` (sync/data agents do).
3. **Side effects need approval** (the YOU gate): sending email, booking meetings, job packages,
   pitches, trades. Agents call `request_approval(ctx, agent, title, payload)` with a unique
   `payload["key"]`; the action runs in an `APPROVAL_HANDLERS[kind]` function only after a recorded
   decision (dashboard, Telegram button, or explicit voice "yes, send it").
4. **Things only Mani can do** (logins, CSV drops) are `bus.notice(key, text, url)` → dashboard
   "Log in" button + Telegram link; cleared with `bus.clear_notice(key)`.
5. **catalog.json is the source of truth** for masters/agents/stages/reporters and must stay in sync
   with the dashboard's `data`/`flows` objects in Main.dc.html.

### Adding or finishing a master
`vision/masters/<id>.py` with `build_agents(options, cfg)` returning `{agent name: SubAgent}` (names must match
catalog.json), optional `APPROVAL_HANDLERS`; register in `LIVE_MODULES` (masters/__init__.py); set
`mode: live` in config.yaml. Agents get `ctx` with `bus, store, cfg, llm, options, results, master`.
Tests: mock HTTP with `httpx.MockTransport`; use `FakeLLM` from tests/test_phase567.py.

### API
`GET /api/state` · `POST /api/boot` · `POST /api/shutdown` (standby) · `POST /api/masters/{id}/run` · `GET /api/brief` · `POST /api/brief/send`
· `GET/POST /api/approvals` · `POST /api/approvals/{id}/{approved|rejected}` · `POST /api/ask {text, session}`
· `POST /api/tts {text, voice?}` → wav · `GET /api/voices` (Kokoro's English voices) · `POST /api/stt` (raw audio body) → `{text}` · `GET /api/traffic?city=`
· `/auth/{google|microsoft}/login?account=` + `/callback` · `/auth/fyers/login` + `/callback` · `WS /ws`

WebSocket events: `snapshot, agent, master_report(+data), boot, log, notice, notice_clear, approval,
approval_decided, telegram, brief, reminder, wake, system, power`.

## Dashboard notes
- Main.dc.html is authored in Claude's canvas "design" format and **must keep that format** (it is also
  published as a canvas artifact). Holes are `{{path}}` only (no expressions); lists via `<sc-for>`,
  conditionals via `<sc-if>`; all logic lives in the `Component` class (`renderVals()` returns flat values).
  `dc-runtime.js` implements exactly the subset used — extend it if you use something new.
- The live bridge is active only on localhost; elsewhere it shows demo data ("PREVIEW · DEMO DATA").
  Live data overrides demo data in `renderVals` (`s.live.*`), so every view still works without the backend.
  **Connected = real data or an honest "waiting / no data yet", never sample values**, on screen or spoken
  (`CON` / `bLive` in `renderVals`). The rule-based local Ask engine is preview-only: when connected and the
  LLM doesn't answer, VISION says the model is offline (`modelOffline`) instead of answering from samples.
- Ask flow: `runCommand` → `askLive` (`/api/ask`) when connected, except navigation commands
  (`isNavCommand`); `{fallback:true}` → `runLocal` (rule-based engine + conversation layer).
- Voice: `speak()` uses `/api/tts` when `voice.tts` is available (rings follow real loudness), else the
  browser voice pinned to a natural female voice (cloud/neural first). `startVoice()` uses `/api/stt`
  (MediaRecorder + silence detection) when available, else browser speech recognition. `wake` event opens the mic.
- Music: `dashboard/audio/inspired.mp3` during the boot roll call, fading into `roadside.mp3` as a quiet loop
  that ducks while VISION speaks or listens. Switch in the voice menu (`vision-music` in localStorage).
- Power button: confirmation → `/api/shutdown` → the roll call in reverse → standby screen; "Power on" calls `/api/boot`.
- Design system: palette #FBCA03 gold, #B97D10 bronze, #AA0505 red, #6A0C0B dark red, #67C7EB blue
  (sparingly), bg #07080A. Fonts: **Michroma** headings, **Pixelywave** body (`dashboard/fonts/pixelywave.otf`, freeware non-commercial, kept out of git), **JetBrains Mono** numbers.
  Rounded corners 8–14 px. Subtle starfield background. No scrollbars (lists fit or page themselves).
  Center: Mani's triangle emblem (`dashboard/core.webp`, pulsing; swells with the voice) with 10 gold diamond icons on one ring (glass hover cards). Mani reverted
  a "sun" core and solar-system orbits — don't reintroduce them.

## Decisions log
- Python backend, no Docker (RAM on 16 GB M1); SQLite; LM Studio for local models.
- Telegram via long polling (no open ports); bot talks only to TELEGRAM_CHAT_ID; briefs 06:00 and 18:00.
- Investments is read-only; rebalancing intentionally removed. Wealthsimple via CSV (no official API).
- Zerodha via hosted Kite MCP (read-only); Fyers via API v3 with daily login (PIN refresh optional).
- Job Hunt: **never touch LinkedIn or Indeed** (not even alert emails). Sources: Job Bank alert emails,
  Adzuna, Greenhouse/Lever/Ashby boards. Never auto-applies; never invents resume content.
- Web Designer images: free stock (Pexels, Pixabay) then Openverse, downloaded as .webp and credited on the page; never
  Google Maps photos or AI-generated images. Unsplash is out (its API forbids rehosting). Pitches need approval.
- Web Designer design: the model only writes JSON (design brief, copy); layout comes from `masters/site_template.py`
  (4 styles: luxe, sunny, trade, editorial), colours from `masters/palettes.json` (ColorHunt) via `pick_theme`.
- Trading: practice account default; live needs OANDA_ENV=live AND options.live_trading: true;
  approval TTL 30 min; refuse if price moved > 0.5 ATR; units capped.
- Weather Agent belongs to News Desk; World Watch is flights only. Film Studio is on hold (stub, disabled).
- Traffic Desk is read-only (no approval gate).

## Status
| Master | Mode | Needs from Mani |
|---|---|---|
| Traffic | live | TOMTOM_API_KEY |
| News + Weather | live | nothing |
| Investments | live | Kite login link, FYERS_APP_ID/SECRET (+PIN), Wealthsimple CSV in inbox/wealthsimple |
| Email / Calendar | live | GOOGLE_CLIENT_ID/SECRET and/or MS_CLIENT_ID/SECRET, accounts in config, sign-in |
| Job Hunt | live | ADZUNA keys, vault/resume/master.md, target titles/companies |
| Web Designer | live | GOOGLE_MAPS_API_KEY, CLOUDFLARE_API_TOKEN + ACCOUNT_ID, optional PEXELS_API_KEY / PIXABAY_API_KEY |
| World Watch | live | optional OPENSKY creds |
| Trading Desk | live | OANDA practice token + account |
| Film Studio | stub, off | on hold (future: GPU worker on Windows PC) |
| Telegram | live | TELEGRAM_BOT_TOKEN, then /start → TELEGRAM_CHAT_ID |
| Ask engine | live | LM Studio server + llm.local_model (optional ANTHROPIC_API_KEY + llm.cloud_model) |

## Next steps (in priority order)
1. **First real run on the Mac**: fix whatever real APIs disagree with the mocks. Most likely spots:
   Wealthsimple CSV column names (ask Mani for the header row only), Yahoo chart endpoint (unofficial),
   Kite MCP tool output shape and login text, Gmail/Graph field edge cases, OpenSky limits.
2. Tune the Ask engine prompt/tools for the specific LM Studio model (tool-call reliability on 7–8B).
3. Wire `dashboard/traffic-map.js` into a Traffic view (Google Maps dark style; needs a Maps JS key).
4. Dashboard: show live job matches / leads / trading calls in their views (data already in
   `report_data`); approvals panel already live.
5. Nightly backup of `data/` and `vault/`; a 05:30 health check (LM Studio, tokens, Telegram).
6. Film Studio as a GPU worker on the Windows PC (later; on hold).

Canvas design of the dashboard: https://claude.ai/artifact/46JvfVBsfsbd5f8FSqaYVf
