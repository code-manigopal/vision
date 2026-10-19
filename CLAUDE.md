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
.venv/bin/python -m vision bgm            # add 3 background tracks per mood to assets/bgm/ (or: bgm sad 5)
.venv/bin/python -m vision fonts          # fetch the ten caption fonts + write the sample sheet data/shorts/_sample/caption-fonts.png
.venv/bin/python -m vision sfx            # add 3 sound effects per kind to assets/sfx/ (or: sfx whoosh 5)
.venv/bin/python -m vision visa list      # Visa Watch accounts: add | list | update | pause | resume | remove | check <id>
.venv/bin/python -m vision ebooks list    # E-books Manager: list | published <book> [ASIN] | redraw <book> <page>
.venv/bin/python -m pytest -q             # 513 tests, all external services mocked
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
  agents.py        SubAgent / StubAgent / Stage / Master; Director (a sub-agent with its own crew); request_approval(ctx, ...)
  orchestrator.py  boot roll call, per-master schedules, 06:00/18:00 briefs, reminders (minutely),
                   approval actions (watches approval_decided -> APPROVAL_HANDLERS[kind])
  server.py        FastAPI: dashboard, /ws, /api/*, OAuth + Fyers login callbacks
  ask.py           AskEngine: LLM tool-calling over master data; session memory 30 min
  voice/           TTS (kokoro | piper | macos), STT (mlx-whisper), WakeWord (openWakeWord), clone.py + indic_f5.py (Mani's cloned Tamil voice)
  channels/telegram.py   briefs (grouped by area with emojis, a long report split into one line per part: `GROUPS`, `ICONS`, `PART_ICONS`, `report_lines`), alerts, reminders, notices, /commands (incl. `/say word = Tamil spelling`, `/say! ...` to force; `/agents`, `/agents <master>`, `/agent <name>` list agents from the live state; `/jobs` with move buttons `jb:<key>:<status>`, `/track <link> [| title | company]`; the menu is set with setMyCommands, `COMMANDS`), approve/reject buttons
  services/        llm.py (LM Studio OpenAI-compatible + Anthropic + a hosted "writer" tier on Groq), oauth.py (Google/Microsoft),
                   reddit.py (official API, read-only), gdrive.py (Drive folder, read-only), bgm.py (music library from Openverse), gutenberg.py (public-domain story books), stock_video.py (Pexels/Pixabay footage), genmedia.py (AI footage provider slot),
                   mailcal.py (Gmail/GCal/Graph), traffic_api.py (TomTom), news.py (Google News RSS),
                   weather.py (Open-Meteo), markets.py (Yahoo chart, CoinGecko, Bank of Canada FX),
                   fyers.py, kite_mcp.py (Zerodha via hosted Kite MCP, persistent session), wealthsimple.py (CSV),
                   nse.py (NSE results filings, read-only), lmstudio.py (unload/reload LM Studio's models around heavy work),
                   world.py (index moves, GIFT Nifty and NSE trading days for the market Shorts), sysmon.py (Instruments: CPU/memory via psutil, GPU via ioreg or nvidia-smi),
                   cfai.py (Cloudflare Workers AI: FLUX.2 klein drawing + Llama 3.2 Vision, free daily neurons counted in kv `cfai`),
                   visa_portal.py (US visa portal for Canada, read-only: Selenium for the person's own sign-in, httpx GETs after), keyvault.py (Fernet key in the macOS Keychain)
  masters/         catalog.json (shared with the dashboard) + one module per live master; market.py + fundamentals.py + market_crew.py + slides.py + tamil_say.py + names_ta.json (Mani Market Tamil)
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
   web=Proposal Drafter, jobs=Application Tracker, world=News Summarizer (news, weather, flights, traffic),
   visa=Slot Watcher, ebooks=Shelf Manager, youtube=Know IDK Things Director (its crew reports to it through Analytics Manager; it also adds Mani Market Tamil's line, whose own crew reports through Market Analytics).
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
· `POST /api/notices/{key}/dismiss` (the Close button: that notice stays away for a day unless its text changes; in memory only)
· `GET /api/issues` · `POST /api/issues/explain {master, agent}` → `{text, source}` · `GET /api/approvals/{id}/email` (full body + attachments) · `GET /api/approvals/{id}/attachments/{att}` (streamed, never stored)
· `GET /api/desk/{master}` (read-only pipeline: stages + items + artifacts; a jobs item also has `actions`, the tracker's next moves) · `POST /api/jobs/{key}/status {status, note?}` · `POST /api/jobs/track {url, title?, company?}` (both local origin only) · `GET /api/files/{path}` (only `data/sites`, `data/applications`)
· `GET/POST /api/visa/accounts`, `POST /api/visa/accounts/{id}` (`{cities, booked, password?}` or `{action: signin|pause|resume|check|forget}`), `DELETE /api/visa/accounts/{id}` (a password is never returned; a request from another origin is refused)
· `POST /api/tts {text, voice?}` → wav · `GET /api/voices` (Kokoro's English voices) · `POST /api/stt` (raw audio body) → `{text}` · `GET /api/schedule` (fire times in the next 24 h of the fixed-time jobs only: master `run_at` runs and briefs, `{at, local, kind, master, label, channel, zone_local?}`; `{standby: true, items: []}` in standby) · `GET /api/traffic?city=` · `GET /api/weather/grid` (globe weather, ~100 points, cached 1 h)
· `GET /api/voice/fix?word=` → `{word, source: fix|table|learned|none, spelling}` · `POST /api/voice/fix {word, spelling, force?}` (Mani's pronunciation fixes; local origin only; 400 with the reason when refused)
· `/auth/{google|microsoft|youtube|gdrive}/login?account=` + `/callback` · `/auth/fyers/login` + `/callback` · `WS /ws`

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
- Holographic deck (`deckOn`, modes `briefing` and `issues`): cards projected from a small copy of the core, cover-flow
  carousel (centre card full, neighbours dimmed and title-only), ← → to step, space to pause. The briefing narrates one
  card at a time (`startBrief` / `deckSpeak`); each desk with something to tell has its own card (key `desk:<id>`, one row
  per part of its report; Mani's choice, 2026-10-13: no combined "Your desks" card); clicking a red agent or asking "what's wrong" opens issue cards and VISION
  explains via `/api/issues/explain`. Tilt, scan lines and tint are switches in the voice menu (`vision-holo`).
  Mode `decide` is the decision deck: one wide card per approval (Review button, or "show my decisions"); a `yt_publish` card shows the video kind and length, a Play link, "Backed by" (each reason with its quote and source, each headline with its publication), the lesson's official pages and the new voice words, and says "nothing recorded" when the payload has none; an email reply
  shows the original beside the draft with attachment chips (`/api/approvals/{id}/email`, previewed in the card), a pitch
  previews its demo site, a trade shows its numbers, reasoning and time left. Decisions never auto-advance.
  Mode `desk` is a master's desk ("Desk ›" in the agent panel, "show my approved pitches", "open the jobs desk"):
  stage chips with counts and one card per record from `GET /api/desk/{master}` (`vision/desk.py`); files and links open
  inside the card (`/api/files/...`, only `data/sites` and `data/applications`). Approved pitches = Web Designer → Pitched.
  `node tests/dashboard_smoke.mjs` runs the dashboard logic without a browser.
- World view: holographic globe (gold wireframe, grid, scan lines; land as dots, bright by day). Aircraft are plane icons
  turned to their real heading with a short trail, coral within `near_km` of home; the hover card shows real progress only
  when the route's origin is known. Weather icons come from `/api/weather/grid` (Open-Meteo); the preview uses a made-up grid.
- YouTube Manager on the dashboard: the agent list shows the Director, then its crew marked `›` (4th value of an agent
  row = the crew's director; live agents carry `director`); the agent graph runs crew stages left to right and ends on the
  Director as reporter. `Component.HOLD` names a master kept on hold (none now). Desk: `desk.youtube` lists every Short by
  status (waiting, unlisted, public, deleted) with script, stats and links.
- "Hey Vision": a browser wake listener (`wakeStart` / `wakeHit`, Chrome speech recognition, switch in the voice menu,
  `vision-wake`, off by default; audio goes to Google while on). It pauses while VISION listens or speaks. Listening mode
  shows on the core: blue ring, blue emblem glow, "Listening…". The backend `wake` event (openWakeWord) triggers the same path.
- Music: `dashboard/audio/inspired.mp3` during the boot roll call, fading into `roadside.mp3` as a quiet loop
  that ducks while VISION speaks or listens. Switch in the voice menu (`vision-music` in localStorage).
- Power button: confirmation → `/api/shutdown` → the roll call in reverse → standby screen; "Power on" calls `/api/boot`.
- 24H timeline (Mani, 2026-10-14): one diamond per fixed-time job from `/api/schedule` (fetched on connect and every 10 min; `run_at` entries may read `"07:02 Asia/Kolkata | label | channel"`), placed by the Mac's clock, colour by channel (Mani Market green, Know IDK Things red, both gold, Telegram briefs blue), hover card with name and time (and IST for a zoned run); the next one is outlined, later-today-already-passed ones dimmed; connected without the schedule it says "schedule: waiting", preview shows a labelled demo.
- Chronograph look (Mani's choice, 2026-10-12): one CSS block at the end of the `<style>` in Main.dc.html restyles the HUD
  (still tick-mark dial round the emblem, one thin red arc, bracket-corner panels, segmented bars, diamond status marks,
  underline tabs, no glow). Delete that block to get the earlier look back.
- Ambient layout (Mani's choice, 2026-10-12): left = Instruments in one row, then Master Agents; clicking a master opens its
  sub-agents (two columns, name + status diamond, status word on hover) and its Desk / Agent graph buttons right under it
  (`accOpen`, `ms.open`, `.acc`); a second click folds them. Opening and folding are a 0.3 s transition: every master
  carries its `.acc-wrap` (grid rows 0fr → 1fr, class `acc-open`), and `accLast` keeps a folding master's list until it has closed. Right = Needs Approval (each notice has Close) then the Activity
  Log (14 lines). Bottom = the 24h timeline alone. The trust badge and agent count show on the selected master only; the
  "Agent graph" side tab is gone (the button does it).
- Design system: palette #FBCA03 gold, #B97D10 bronze, #AA0505 red, #6A0C0B dark red, #67C7EB blue
  (sparingly), bg #07080A. Fonts: **Michroma** headings, **Pixelywave** body (`dashboard/fonts/pixelywave.otf`, freeware non-commercial, kept out of git), **JetBrains Mono** numbers.
  Rounded corners 8–14 px. Subtle starfield background. No scrollbars (lists fit or page themselves).
  Center: Mani's triangle emblem (`dashboard/core.svg`, a vector redraw of the original `core.webp`, which stays in the repo; swells with the voice) with 10 gold diamond icons on one ring (glass hover cards). Mani reverted
  a "sun" core and solar-system orbits — don't reintroduce them.

## Decisions log
- Python backend, no Docker (RAM on 16 GB M1); SQLite; LM Studio for local models.
- Telegram via long polling (no open ports); bot talks only to TELEGRAM_CHAT_ID; briefs 06:00 and 18:00.
- Investments is read-only; rebalancing intentionally removed. Wealthsimple via CSV (no official API).
  The report (Daily P&L Reporter) carries, beside the day's P&L: `overall` (worth against cost, for holdings whose broker gives
  a cost: Zerodha/Fyers `cost`, Wealthsimple `book_cad`; as % on cost and as % of the portfolio) and `overall_ports` (the same broker by broker, each in its own currency, then the CAD total), `gainers` / `losers` (the day's
  top 3 each, with share of portfolio and the Market Watcher's news on them) and `ideas` (up to 3 options to weigh, from the
  local model, else from plain rules in `rule_ideas`; `ideas_by` says which). Ideas are wording only, never orders; nothing trades.
  The briefing deck shows them as cards (Top gainers, Top losers, What you could do).
- Zerodha via hosted Kite MCP (read-only); Fyers via API v3 with daily login (PIN refresh optional).
- Job Hunt: **never touch Indeed** (not even alert emails). Sources: Job Bank alert emails,
  Adzuna, Greenhouse/Lever/Ashby boards. Never auto-applies; never invents resume content.
  **LinkedIn (Mani's choice, 2026-10-12, reversing the earlier "never"; switched off the same day, `linkedin: false`: the
  first live request was answered 429, so a browser's user agent alone does not get in, and going further was not pursued):**
  `linkedin: true` reads LinkedIn's public job search
  as a signed-out visitor with a browser's user agent (`jobs.linkedin`, `LI_UA`; against LinkedIn's terms, his call). Limits
  in code, keep them: never signed in and no cookies (so his account is not involved), `linkedin_titles` (4) result pages and
  `linkedin_details` (10) posting texts a run, `linkedin_delay` (4 s) apart, and a 403/429/999 or a redirect to the sign-in
  wall stops it for a day (kv `job_state` `linkedin`): no retry, no proxy, no CAPTCHA handling. LinkedIn alert emails are
  still not read. The page parsing was written from the known page layout and has never read a live page.
  Borrowed after reviewing five open-source job hunters (2026-10-12; career-ops, ai-job-hunter-app, ai-job-search):
  `masters/job_match.py` (plain rules, no model): whole-word skill matching with other spellings (`has`, `ALIASES`; "Excel"
  is not in "excellent"), `coverage` (skills the posting names that the resume shows, and `gaps` it doesn't: shown on the
  desk and given to the tailor as never-claim), `gate` (ruled out before scoring, from the posting's own wording, silence
  never fails: citizens-only or PR-only against `work_status`, a required clearance, required French), `same_keys` (one
  identity for a job seen from two sources or listed again: kv `job_keys`, the later one is stored as `duplicate`, the
  first gets `reposts`), `ats_ref` (a posting link on Greenhouse/Lever/Ashby/Workable/SmartRecruiters adds that company to
  kv `job_companies`, read on later runs: `known_companies`) and `fence` (posting text marked as data in every prompt).
  `masters/job_facts.py` `unsupported`: a reworded resume must keep every heading and add no skill, number or name the
  original lacks, or the resume goes in as written with the reason (`tailor_note`); a cover letter naming a skill the
  resume lacks is rewritten once, and what remains is shown (`letter_note`). A posting with under 200 characters of text
  is `provisional` (title only: half marks for skills, "~" on the desk, no model score). The Tailor drops a posting whose
  page answers 404/410 (`expired`). The Tracker reminds after `followup_days` (10) with no reply, `followups` (2) times,
  then sets the application aside after `stale_days` (60). `work_status: permit` (Mani holds a post-graduation work permit, 2026-10-12): postings open to citizens only, or to
  citizens and permanent residents only, are ruled out; update it when his status changes.
  Adzuna is no longer free (25 test calls, then £8 a month, seen 2026-10-12): `adzuna_titles: 0` keeps it unused. Free feeds
  with no key (`free_sources`): Job Bank's search feed (Ontario, only the last couple of days, its own job names), Himalayas
  and Jobicy (remote jobs open to Canada); company pages also on Workable and SmartRecruiters (titles only, no description).
  **Mani's rule (2026-10-12): Ontario only, postings from the last 14 days** (`region: Ontario`, `in_ontario`; `remote_ok: true` also keeps
  remote jobs that say they are open to Canada). The Muse was tried and dropped (old postings, loose location filter). Three resumes in `vault/resume/` (git-ignored):
  `analyst.md`, `software.md`, `ai.md`, converted word for word from Mani's .docx files and picked by the posting's title
  (`resume_for`); `master.md` (a copy of software) is the fallback. The AI resume was built from the software one
  (`Kanaga_Manikandan_Gopal_AI_Engineer.docx`, same styles) with a VISION project section; re-convert after he edits a .docx.
  Resume Tailor never blocks the chain: the model (`tailor_tier`, `tailor_timeout`) gets the resume without its name and
  contact lines (`split_contact`); a timeout, an error or a cut-down answer leaves the resume as written (`reworded: false`).
  The local 8B model timed out on a full resume (2026-10-12), so **Mani chose Groq** (`tailor_tier: writer`).
- Web Designer images: free stock (Pexels, Pixabay) then Openverse, downloaded as .webp and credited on the page; never
  Google Maps photos or AI-generated images. Unsplash is out (its API forbids rehosting). Pitches need approval.
- Web Designer keeps a stack of 5 demos in play (`options.stack`): being built, live, or awaiting a decision.
  Approving or rejecting a pitch frees a slot and triggers a refill run straight away. When the area runs short of
  new businesses it moves on to other business types (`MORE_TYPES`, after `business_types`), then the search radius doubles by itself (`radius_km` up to `max_radius_km`, default 50).
- Web Designer stays inside Google Places' free allowance: at most `builds_per_day` (5) new leads a day; every no-website business a search returns goes into a pool
  (kv `candidates`) that refills the stack with no API call; a (type, radius) search isn't repeated for 30 days
  (kv `web_searched`); and calls stop at `places_monthly_budget` (800) a month with a dashboard notice.
- Web Designer design: the model only writes JSON (design brief, copy); layout comes from `masters/sitekit/` — a section
  library (3 navs, 8 heroes, 5 services, 4 galleries, 3 reviews, steps, FAQ, call band) combined into 14 curated styles
  ("recipes": foreman, forge, clinic, artisan, gazette, atelier, sprout, noir, mainstreet, swiss, bloom, chalkboard, harbour,
  parlour; 4 dark), each with its own type pairing and shape language. `recipes_for(type)` lists the ones that suit a business;
  `choose_style` gives every demo in play a different one. Colours: `masters/palettes.json` (ColorHunt) via `pick_theme`,
  expanded by sitekit into light or dark roles that pass AA contrast. `site_template.py` is only a shim.
  A fifteenth style, `classic` (`sitekit/classic.py`), is the original one-layout page Mani liked (luxe, sunny, trade or
  editorial by business type), kept with two fixes: content shows without scripts, and the gallery heading fits the business.
  `styles_for(type)` = the recipes that suit the business plus `classic`.
- Web Designer style choice (`masters/site_style.py`): reasoned, not random. Each suitable style is scored against the business's
  own reviews, Google summary and name (traits: warm, refined, bold, practical, playful, calm, modern, traditional, formal, dark);
  a style is marked down for what it says that the business shows no sign of; the model's pick is one signal; a style used by
  another demo in play is passed over. With nothing to go on, the usual fit for the type wins. The palette follows the style
  (`palette_moods`). The reason is saved as `style_why` and shown on the desk card.
- Web Designer copy (`masters/site_copy.py`): wording and section titles by business category; unsupported claims are removed
  (years, awards, licensed/insured, guarantees, 24/7, prices, counts, staff names) unless the business's own Google data says so;
  the service area comes from the address. No model, or junk twice → plain copy from the lead's facts.
- Web Designer photos (`masters/site_images.py`): trade-specific searches; a photo is used only if its description matches the
  trade, and gets a role (hero, about, gallery). Fewer photos rather than unrelated ones.
- Web Designer quality gate (`masters/site_qa.py`): every page is checked before it can be deployed (structure, leftovers, tel
  link, disclaimer, images, contrast, phone-width overflow, content visible without scripts). A layout fault is retried in up
  to three other styles; a page that still fails is kept as `draft.html` with status `qa_failed` (desk stage "Held back"),
  never deployed or pitched. `scripts/site_contact_sheet.py` renders every style for sample businesses into
  `data/sites/_contact/index.html`.
- Photo tours (a walk-through of a home from its listing photos and floor plan) were tried on 2026-10-12 and **parked**:
  the code is on branch `parked/photo-tour` (commit ad8ea3f), not on main; its CLAUDE.md there has the full write-up. Why
  parked: one photo per room places the camera right only about a third of the time, furniture smears when painted onto
  flat walls, and capture-based tours (Matterport, iGUIDE, Zillow) already do it properly. Left on this Mac: the tours in
  `data/tours/`, the test home in `data/dummy_home/`, `models/depth-anything-v2-small.onnx` (99 MB), and Blender.
- Trading: practice account default; live needs OANDA_ENV=live AND options.live_trading: true;
  approval TTL 30 min; refuse if price moved > 0.5 ATR; units capped.
- **World Watch is everything VISION watches in the world: news, weather and flights (Mani, 2026-10-13). News Desk is no longer a
  master**: its four gatherers and the Weather Agent run beside the Flight Tracker (stage GATHER, none of them blocking), then
  the News Summarizer reports for the master (stage CURATE): headlines, weather, the Flight Tracker's line, and the flights in the
  same report data (`report_data.world`: `headlines`, `weather`, `flights`, ...). The news agents stay in `masters/news.py`,
  built by `world.build_agents`; settings are under `masters.world.options`. The master cycles every 15 min for the flights;
  the feeds are read again only every `news_minutes` (30). The globe's weather icons are a plain data endpoint, not an agent.
  OpenSky without an account allows about 100 world snapshots a day (a 429 after that): a refusal is a wait, not a fault
  (label RESTING, the last flights stay up, nothing asked until the allowance is back: kv `world_state`), hence 15 min.
  World Watch shows `near_slots` (10) flights nearest home first, the rest spread worldwide; a route lookup is spent only on callsigns not yet known.
- **Traffic Desk is no longer a master (Mani, 2026-10-14): merged into World Watch**, read-only as before (no approval gate). City Geocoder
  runs in GATHER beside the news, then Traffic Poller (stage ROADS) and Incident Scout (INCIDENTS); none of them blocks (no TomTom key = red Geocoder,
  the other two idle WAITING, the news still reported). The News Summarizer adds the Scout's line to the report and the cities to its data (`traffic`).
  Agents stay in `masters/traffic.py`; `watch_cities` is under `masters.world.options`; checked every World Watch cycle (15 min). `/api/traffic`,
  `/traffic` on Telegram and `python -m vision traffic` are unchanged. Its slot on the ring goes to the E-books Manager (to be designed).
- Visa Watch (`masters/visa.py`, added as the 11th master, now one of ten; Mani and family only, **notify only, Mani books by hand**): about once an
  hour per account (`interval_minutes` 60 ± `jitter_minutes` 10; the master cycles every 10 min and looks at one due account
  per run, never two within 5 min unless `test_mode: true`) it reads the dates the Canada portal (ais.usvisa-info.com) offers
  for the chosen cities; a date strictly earlier than the booked one raises a notice (dashboard + Mani's Telegram), once per
  city + date per 24 h. Built the way the open-source kcajc/usvisa-ca works (**Mani's choice: Selenium, not Playwright**),
  minus its rescheduling. Sign-in is a visible Chrome window Selenium opens. Default: the account holder signs in themselves
  ("Sign in" on the desk, or `python -m vision visa signin <id>`; VISION types nothing, no password kept). **Mani's choice
  (2026-10-07): an account may carry a password (optional field, Fernet-encrypted, never returned by the API), and then
  VISION signs in itself as the repo does**, once per expired session and at most `MAX_SIGN_INS` (8) a day; a refusal, a
  lock message or a CAPTCHA pauses the account and nothing retries (an automated attempt that day got sign-in locked for
  an hour). The
  session (cookies, that browser's user agent, the schedule number) is kept Fernet-encrypted in `data/visa/*.session`, key
  in the macOS Keychain (`services/keyvault.py`). The hourly look is plain httpx with those cookies and that user agent
  (Mani's choice), GET only (`_only_get`), no browser: one request per city to the portal's days list (consulate numbers
  in `FACILITIES`). A session that has run out puts the account in status `signin` with a notice; it is not a failure.
  A CAPTCHA page in an answer pauses at once, three failures in a row pause, no retries, no proxies.
  Accounts are in kv `visa_accounts`. usvisascheduling.com (India) is parked: add it to `visa.PORTALS` and `visa.SIGNERS`.
  Nothing has run signed in yet; how long the portal keeps a session is unknown.
  Dashboard: "Desk ›" on Visa Watch opens the accounts panel (`openVisa`, `visaOn`): list with Sign in / Check now / Pause /
  Edit / Remove (asks first) and an add form (name, sign-in email, optional password, cities, the date to beat).
  Each account has an accepted range agreed with its owner up front and editable any time: `not_before` (optional) up to
  `booked` ("alert if earlier than": a booked appointment's date, or any target date when nothing is booked yet), minus
  `skip` (days or ranges never to offer, typed as `2027-03-10, 2027-04-01..2027-04-07`). `earlier()` passes over an
  unacceptable date and takes the next one. An empty list from the portal is reported as "portal lists no dates" (it can
  mean nothing on offer, a finished application, or the portal holding back). **Planned, not built: Approve on Telegram →
  VISION books that exact date (re-checked first, approval expires); to be written in dry-run first and only tried on an
  account with an open application. With it, a per-account "book by itself if in range" checkbox (Mani, 2026-10-07: some
  owners give full authority over dates), off by default: on = the first acceptable date is booked without asking, once,
  then the account stops looking and Mani is told; off = Approve / Reject as above.** The portal
  only lists dates for an account with an open application (a schedule number); Mani's own June 2026 appointment is done.
- **E-books Manager** (`masters/ebooks.py` + `ebook_art.py` checks + `ebook_print.py` PDFs; Mani, 2026-10-14; took Traffic Desk's slot): KDP
  paperback coloring books for children under the brand **Grow Kids Max Studio** (author field), one book at a time, **quality before volume**,
  **zero cost**. Theme Planner (`options.queue` "Theme | ages", then `THEMES`) → Page Writer (Groq `options.model`, pictures + spares scenes,
  brand/character names refused, `BRANDS`) → Illustrator (Cloudflare FLUX.2 klein 1024x1328, `tries` per page per round, stops before
  `neuron_budget`; a used-up allowance is RESTING, never an error; carries on after 00:00 UTC) → Page Inspector (code: `ebook_art.issues`
  grey > 0.30 after a median filter, solid black > 3 %, hairlines, empty/too dense, spaces too small for the age, near-copies by dHash; then
  Llama 3.2 Vision on Cloudflare: deformed, letters in the picture, scary, off-scene, score < `min_score`; best passing try wins; after `rounds`
  a page is dropped and a spare steps in; spares used up = the writer adds scenes) → Book Builder (pure black and white 300 DPI inside the
  safe area, interior PDF: title, copyright with the AI note, "This book belongs to", each picture on a right-hand page with a blank back,
  thank-you) + Listing Writer (Groq; `HYPE`/`BRANDS` refused, categories only from `CATEGORIES`, price by rule `ebook_print.price`: band
  6.99-9.99 and royalty >= 1.75 from KDP's print-cost estimate) + Cover Designer (colour FLUX art with no text, every word set in code,
  spine from the page count, barcode box empty; waits for the listing's blurb) → approval `ebook_publish` (Shelf Manager raises it once per
  version) → Mani uploads to KDP himself (no KDP API; a bot on KDP breaks its terms), then `ebooks published <book>`. Groq has no vision
  model on Mani's key (llama-4-scout gone), hence Cloudflare's. Drop-ins `inbox/ebooks/<book>/page-07.png` / `cover.png` replace a page or
  the cover art, rebuild and ask again (an older approval is answered "outdated"). Thresholds were calibrated on Mani's own Gemini book
  (`~/Downloads/Animals_Thematic_Coloring_Book_A4.pdf`, his quality bar). Gemini's image API is not free; Pollinations' terms unclear; the
  Gemini app is by hand only. Not built: edutainment/activity pages, story books, KDP sales CSV, dashboard Redraw button.
- **One Vision folder in Drive (Mani, 2026-10-18):** everything VISION keeps in kamanikagopal's Drive sits under `Vision/` (`gdrive.TOP`,
  `gdrive.vision_path`): `Vision/YouTube/<channel name>/{Shorts,Videos}` and `Vision/Jobs/<package folder>`. A channel's older top-level
  `backup_folder` (an older top-level folder, e.g. mani_market_yt) is moved in and renamed the first time (`legacy`), nothing re-uploaded.
  `backup: true` switches backups on without one (`youtube.backs_up`).
- **Job tracker (Mani, 2026-10-18, like LinkedIn's My Jobs):** approving a package sets `approved` (not applied: dashboard and Telegram say
  Approved); Mani marks it applied (that date starts the follow-ups), then interview, offer, rejected or archived (`jobs.TRACK`, `NEXT`,
  `set_status`, history kept on the record), on the desk's card buttons or Telegram /jobs. An "application received" email moves an approved
  job to applied. `jobs.track` adds a job applied to elsewhere (status applied, source "added by you"; only its public page is read, for the
  title; Indeed links refused). Approved and later packages go to Drive (`jobs.to_drive`, same `drive-backup` sign-in, every file checked by
  size and MD5) and only then is `data/applications/<folder>` deleted (`local_removed`; the desk links "Files in Drive"); approval tries it
  at once, the Application Tracker again each run. Rejected packages stay on the Mac. `legacy_approved` turns the jobs the old code marked applied on approval (applied, no `history`) into approved; ran live 2026-10-18 (21 jobs, 84 files to Drive).
- **Video backups to Drive (Mani, 2026-10-15: "this is for backup... no more local saves"):** each channel's `backup_folder`
  (now under Vision/YouTube/<channel name>) in kamanikagopal@gmail.com's Drive, sub-folders `Shorts` / `Videos`, files named
  `youtube.backup_name` ("2026-10-15 <title without hashtags> [<video id>].mp4" + " cover.jpg"). `youtube.backup` runs in the Analytics
  Manager / Market Analytics after videos.list has confirmed the video; each file is uploaded resumable (`gdrive.upload`) and checked by size
  and MD5; only then may `free_space` delete the local folder. Own sign-in `drive-backup`, oauth provider `gdrive`, scope `drive.file` (it sees
  only what VISION created, so it makes its own folders of those names; the two Mani made by hand are not used). No sign-in, a full Drive
  (notice `gdrive-full`) or a mismatch = the local files stay and it tries again next run.
  **Monthly clean-up (Mani, 2026-10-15):** on the first run of each month `youtube.prune_drive` moves to Drive's trash (Drive empties it after 30
  days) the backups of videos released before this month that videos.list has just seen public; a video gone from YouTube keeps its copy.
  Marked done per month in kv `yt_state` `<channel>:drive_prune:<YYYY-MM>`, only once every such video was confirmed that run.
  `_refresh` now asks videos.list in batches of 50, so every video is followed (it used to look at the first 50 only).
- YouTube Manager (`masters/youtube.py`, took the Film Studio slot) has three levels: master → one Director per channel
  (`options.channels`) → that channel's crew. `Director` (agents.py) runs its crew like a master runs sub-agents; crew
  agent events carry `director`. Crew for Know IDK Things: Story Scout → Story Writer → Screenplay Writer →
  Keyword Generator + Voice Artist + SEO Strategist → Footage Collector → Footage Generator → Editor → Uploader → Analytics Manager.
  **Mani's choice (2026-10-06): no review at all for Know IDK Things.** `privacy: scheduled` uploads each Short as
  private with a publishing time: the first `publish_times` slot after the last release already scheduled (`next_slot`;
  the releases are one queue in upload order, never filled into an earlier gap; the Uploader first refreshes every
  video's `publishAt` so Mani's hand-set times count), and YouTube makes it public by
  itself; no notice is raised. His rhythm: four a day, released at 06:00, 12:00, 18:00 and 00:00. The master runs every morning
  at 05:00 (`run_at` on the master, a cron job beside the six-hourly cycle) to make, upload and schedule the day's four;
  `create_after: "05:00"` keeps a night-time cycle from starting the day's Shorts early. (`privacy: unlisted` is the earlier mode: a notice with the Studio link, public or delete by
  hand.) A private video with a `publishAt` counts as `scheduled`, whether VISION or Mani scheduled it. Analytics Manager checks each uploaded Short
  (status, views, likes, comments), clears the notice once it is public or deleted, and its report feeds the briefs.
  Sign-in per channel: `/auth/youtube/login?account=youtube-<channel id>` (oauth provider `youtube`, same Google app).
  Stories come from `inbox/stories/<channel id>/*.txt` (first line may be the source URL); the Scout first copies new
  Docs and .txt files from the channel's Google Drive folder (`drive_folder`, `services/gdrive.py`, read-only, same sign-in
  as YouTube, fetched ids in kv `yt_drive`) into that inbox. Reddit's official API is wired in but asleep: Reddit now makes
  new accounts register for API access before an app can be created, and a monetised channel may be refused;
  **Quora is out** (no API). With `originals: true`, when no real story is waiting the Scout takes a premise from its bank
  (kv `yt_premises`; refilled in batches by the model from code-picked ingredients THEMES x SETTINGS x TELLERS x TURNS, each
  premise used once, near-duplicates dropped) and the Writer writes an original, fictional true-to-life story: never
  framed as real or as "someone shared", marked `original` in the log, "This story is fiction." in the description.
  Other sources, in the Scout's order: long comments under the channel's own Shorts (`viewer_comments`, kind `viewer`) →
  Drive/inbox/Reddit → one classic a day (`classics`: Project Gutenberg book ids, `services/gutenberg.py` cuts a book at its
  capitalised headings into `data/classics/<id>/`; retold faithfully with the author's ending, citation spoken as the last
  line and in the description; used stories in kv `yt_classics`) → originals. Every Short carries the invitation to share a
  story: the spoken `outro`, the `cta` line in the description and the channel's own comment (the API cannot pin it;
  Mani pins by hand). `playlists` maps a story kind to a playlist (classics → "Classic Stories"), created if missing.
  Playlists and comments need the `youtube.force-ssl` permission: `can_manage()` checks the sign-in's recorded scope and
  raises a "sign in again" notice without stopping uploads. VISION never deletes a video.
  **Long videos** (`long:` on the channel, defaults in `LONG`): one a day beside the Shorts, wide 1920x1080, 6-9 minutes, a
  classic with at least `min_source_words` (1600). Written **chapter by chapter on Groq** (Mani's choice over the local
  model): `parts()` cuts the original into 3-6 pieces and each request retells only its piece, which keeps every request
  under Groq's 8,000 tokens a minute; one more small request gives title, cover words, summary, hashtags, mood. Beats are
  grouped into shots of about `shot_seconds` (8) that share one clip (`shot` on a beat; a Short's beats are each their own
  shot); keywords and footage are per shot; `assemble(wide=True)` joins beats with the same footage into one segment.
  The Editor makes `thumb.jpg` (`shorts_edit.thumbnail`: a stock photo, darkened, with the writer's 2-5 words) and the
  Uploader sets it, adds chapter timestamps to the description and puts the video in `long.playlist`. Long videos have
  their own release queue (`next_slot(fmt="long")`, daily at `long.publish_time`) and are made in the 03:00 run
  (`long.create_after`), apart from the Shorts, to stay inside Pexels' 200 requests an hour.
  **SEO Strategist** (crew, PREP stage, `blocking = False`): packages each video before upload. It asks YouTube's own
  search-suggestion endpoint (`services/yt_suggest.py`, unofficial, no key) what people type for the video's subject, adds
  the channel's best-performing titles (kv `yt_state` `<channel>:insights`, written by the Analytics Manager from public
  videos' views), and has the model give a title under 60 characters, the description's opening lines, 8-12 search tags
  and 3 hashtags. Guard rails in code: fiction is never titled "true", tags for a different video (other languages, "for
  kids", "official") are dropped, tags stay under YouTube's 500 characters. No answer = the writer's title stands.
  **Reach is YouTube's decision (clicks and watch time); nothing here buys or fakes engagement, and nothing should.**
  YouTube caps uploads per channel per rolling day (hit on 2026-10-06 after about ten in 24 hours, deleted ones included;
  error `uploadLimitExceeded`). The Uploader treats it as a wait, not a fault: a notice, the Shorts stay `ready` and go up on
  a later run; and the Scout makes no new Shorts while `shorts_per_day` or more are waiting (label BACKLOG).
  Originals come in kinds that take turns (`original_genres`): life, motivational, and science (48 subjects across
  space, earth, forests, oceans in `SCIENCE`; a subject isn't repeated while others are unused). Each kind has its own
  premise request and writing rules (`GENRE_ASK`, `GENRE_WRITE`); science must stay with established facts and leaves
  out any number it isn't sure of, but **nothing checks its facts**. Kinds `science` and `motivational` have their own playlists.
  A fourth kind, `money` (honest money lessons, 32 subjects in `MONEY`, playlist "Money Lessons", "not financial advice" in
  the description): established principles only, what a thing costs and risks as well as what it gives, **never a promise
  of an amount, a speed or a certainty of earning** (Mani's rule: explore, don't promise: "how can we make...", "can you really...", said as
  may-or-may-not. `promises(title)` refuses a title that states such a thing but allows it asked as an open question, so
  "Get Monetized in 3 Days" is refused and "Can you get monetized in 3 days?" passes; `TOLD_PROMISE` refuses a lesson
  that promises the viewer money, while a myth being examined may be named). Learning videos
  (money, science) are built on one of Mani's four watch-to-the-end patterns (`STRUCTURES`, from his two tables: result first, belief
  contradicted, better then best, won't work unless, only if done one way, not A / not B / C pays off, most do this and get
  least; plus `HOLD_BACK`: never the whole answer before the final third), the least used so far, saved as `structure` and compared in
  insights (`views_by_structure`); stories get the `RETAIN_STORY` rule (open a question, raise the stakes mid-way, answer last).
  Opening shapes (`HOOKS`, reworked from hook sheets Mani collected): ten for stories (third person; the narrator has no
  "I", so nothing claims a personal result) and twelve for lessons (spoken to "you"). An original story's first sentence
  follows its shape; a lesson's shape goes to its title via the SEO Strategist, because its script already follows a
  pattern. Chosen like the patterns (least used, then by `views_by_hook`), saved as `hook`.
  Trends (`trends`, `trend_region`, `services/yt_trends.py`): the Scout reads YouTube's most-popular chart (overall plus
  three categories, one quota unit each, at most twice a day, kept in kv `yt_state` `<channel>:trends`). It is mostly
  music and gaming, so it is used narrowly: a money or science subject sharing a telling word with it is planned and
  picked first (`trend_score`), and the SEO Strategist sees only the chart titles that touch its video. Lesson titles
  stay open questions; an opening shape is borrowed only as a question the lesson really answers.
  Groq's free allowance is 8,000 tokens a minute and 1,000 requests a day; `llm.py` waits and retries on a 429.
  Real stories always go first. **Mani intends to monetise**: YouTube's "inauthentic content" policy is the standing risk
  for AI-written stories; variety and his review before publishing are the mitigations. A story is screened by rule and by the model (no clear yes = not used), retold in the third
  person with no names or places, and split into beats by code, not by the model. The voice speaks whole sentences
  (fragment-by-fragment sounded like reading) and each sentence's audio is divided between its beats; the real audio sets
  the timeline. The writer names the story's mood (dark, sad, warm, light, dramatic) and the channel's `voices` table maps a
  mood to engine, voice, speed and pause; other moods use `voice_engine` / `voice` / `voice_speed` / `pause`. Engines: `edge`
  (reports word timings) and `kokoro` (local; mlx-whisper "small" then listens to each sentence to time its words, because
  **Mani wants no caption drift**; "base" skips words, don't use it). `align()` maps heard words onto the script's words.
  `shorts_per_day` (5) is the daily number; one run keeps making Shorts until it is reached (`Director(again=...)`).
  The day's count goes by each record's `made` time; `youtube.reset_today(store, channel_id)` starts it again (kv `yt_state`). One clip or photo per beat, ranked by its own description.
  Editing: clips get a slow zoom (`motion`). Captions take a look by mood from ten fonts (`services/fonts.py`, `style_for(mood, kind, turn)`;
  `python -m vision fonts`, sample sheet `data/shorts/_sample/caption-fonts.png`; money/science have their own; the spoken word is highlighted;
  long videos keep captions low; `caption_styles`). Sound effects (`services/sfx.py`, CC0 only, `python -m vision sfx`, `assets/sfx/<kind>/`):
  **Mani's rule: a sound effect only where the sentence needs it, chosen by that sentence's mood.** The Keyword Generator
  asks the model, line by line, for one cue from `CUES` (riser, impact, heartbeat, drone, tick, ding, whoosh, pop, coin,
  notification; only kinds the library holds) or "none", most lines none; `sfx_plan` places each at its line, keeps them at
  least 4 s apart and about one per 8 s, and never adds any on its own (`sfx`, `sfx_volume`). No model answer = no effects. The record keeps `caption` and `sfx`; both show on the desk.
  **Know IDK Things (Mani, 2026-10-18; the channel covers science, money and stories, and will grow):** channel id `knowidk` (sign-in
  `youtube-knowidk`, kv keys `knowidk:...`, inbox `inbox/stories/knowidk/`, Drive inbox "Know IDK Things Inbox" in knowidkthings@gmail.com's Drive,
  work folders `data/shorts/knowidk/`; `scripts/migrate_knowidk.py` moved the older data over). The outro and comment invitation both ask
  "Have a story to share? Drop it in the comments" (Mani's wording, so viewers' stories keep coming for `viewer_comments`). The original story kind
  is `life` (a true-to-life story: an ordinary adult did or hid something and it comes out). Mani's rule: no word for the channel's former theme
  anywhere in VISION. Its Drive backups are in Vision/YouTube/Know IDK Things. Its logo (`assets/brand/`: the sticker
  cut from its baked-in checkerboard as know-idk-things.png, plus Mani's round logo, banner and the original) is the watermark (`logo`, top right,
  150 px at 80 %; a logo path is taken from the repo root). A copy of all four is in Drive, Vision/YouTube/Know IDK Things/Brand (2026-10-18). Mani renames the channel and handle in YouTube Studio.
  **No sexual content (Mani, 2026-10-18: "no more such contents"):** `SEXUAL` (sex, lust, fantasies, role-play, nude, one-night stand...) rejects a story
  from any source by rule before the model sees it; the screening prompt also rejects one where sex or sexual desire is any real part; a written script
  that matches is sent back to be rewritten. Strict on purpose (a harmless "aroused from sleep" also stops a story).
  **Daily mix and YouTube Analytics (Mani, 2026-10-18: "daily two videos are of science, one from stories and one for finance"):** `daily_mix`
  `{science: 2, story: 1, money: 1}` replaces `shorts_per_day` for the channel: the Scout fills the category with most slots still open
  (`next_category`, `made_by_category`; story = real, viewer, classic or an original life story, never motivational; science/money = an
  original of that kind, `_original(ctx, want)`); a real story that finds the story slot used waits for tomorrow. The Analytics Manager reads
  YouTube Analytics API v2 (`services/yt_analytics.py`, scope `yt-analytics.readonly`: one more YouTube sign-in, notice
  `youtube-analytics-<channel>`; "YouTube Analytics API" must be enabled on the Google app) at most every 6 h for public Shorts 2+ days out:
  views, engaged views (dropped if the API refuses them), average view duration and percentage, subscribers; kept as `analytics` on the record.
  `category_scores` (last `mix_days` 28): score = average of views x share watched + 50 per subscriber; shown in the report ("watched: ...").
  `mix_auto: true`: once a week `resplit` shares the same total by score, at least 1 each, a category with under `mix_min_videos` (6) measured
  Shorts keeps its slots; kept in kv `yt_state` `<channel>:mix`, a change is logged and sent to Telegram (a `reminder` event) with the figures.
  The report's "latest" is the last made (it followed the store's save order and flipped).
  **Animated diagrams (Mani, 2026-10-18; `masters/scenes.py`, HyperFrames):** channel option `diagrams` (kinds: science, money, story; all three on
  in config, Mani approved the samples 2026-10-18). The Footage Generator asks the model which lines a diagram explains better than footage (at most 40 % of a Short's
  lines, never line 0 or the outro; a story at most 2) and for a template + short labels as JSON, never HTML; `scenes.check` keeps a scene only if
  the template is known for that kind, labels are short and every figure on it is one the spoken line says (finance: nothing matching `PROMISE` /
  `TOLD_PROMISE`, a growth curve has no figures and always says "Illustration, not a promise", breakdown shares only when the line gives them all
  and they make 100; story: chat messages are the line's own words, a quote is copied whole from the line; a flow with a bad step is refused,
  never shortened). Templates: science orbit, compare, flow, cycle, number; money compare, number, growth, breakdown, myth, checklist; story chat,
  quote, timejump, split. A Short's scenes render in one go (`render_shots`) and are cut per beat; the visual has `diagram` (the Editor adds no
  zoom), source "diagram" (not in the footage credits); the record keeps `diagrams`. Any trouble = the beat keeps its stock footage.
  `scripts/short_sample.py science|money|story` makes a Short with the real crew on a throwaway database (nothing counted or uploaded).
  **Quick Shorts** (`quick`, `QUICK`: 20-35 s, ends on its own outro, `per_day` 1, 0 = off): only an original story can be one (Scout sets
  `job["quick"]`), counted among the day's Shorts; `word_range(ch, quick=True)`; insights keep `views_by_length` (quick vs regular).
  **Double down** (`double_down`, `double_down_after` 12, `explore` 0.15): `choose(options, told, views, floor)` gives each option a floor share
  and the rest by average views; the Scout uses it for the original kind (`views_by_kind`, a life story counts as "original") and the learning
  pattern (`views_by_structure`) once insights have enough public videos, else the least-told as before; the floor is held to 70%/options so
  seven patterns still lean.
  Background music is a library on disk, `assets/bgm/<mood>/` (git-ignored), filled by `python -m vision bgm [mood] [count]`
  from Openverse (`services/bgm.py`: CC0 / public domain / CC BY only, tagged instrumental, never sung) or by Mani dropping
  files in; each fetched track has a `.json` credit. The Editor takes the next track for the story's mood, levels it
  (`loudnorm`), mixes it at `music_volume` (0.12, about 14 dB under the voice) and fades it out; the Uploader adds a
  "Music:" credit line. No track for the mood = no music. NCS is not used (not open, no API).
  `masters/shorts_edit.py` renders 1080x1920 with ffmpeg + Pillow (Homebrew ffmpeg has no subtitle filter, so captions are
  drawn as images); every segment must share one pixel format and colour range or the overlays reset mid-video.
  Output: `data/shorts/<channel>/<date-slug>/final.mp4`; log in kv `yt_videos` (source URL, script, screenplay, keywords,
  credits), seen stories in kv `yt_seen`. **Local copies (2026-10-15, the disk filled):** each Analytics Manager / Market Analytics run (`youtube.free_space`) deletes
  the folder of a video a videos.list call found on YouTube after its upload (Mani: "check and make sure it is there", never the upload's answer
  alone: `on_youtube`; status scheduled/public/private; record kept, `local_removed`, desk "Local files: removed after upload"),
  and `build/ audio/ footage/` of an unrecorded run untouched for 2 days; ready/awaiting/review/stale/deleted keep theirs. `keep_local: true` keeps all. Footage Generator is a provider slot (`services/genmedia.py`, `generator:` per
  channel), off until a provider is named. Writing uses `llm.writer_model` on Groq (reasoning models need large max_tokens).
- Mani Market Tamil (`masters/market_crew.py`, a second channel `manimarket` under the YouTube Manager: `crew: market` in the channel's options makes
  `youtube.build_agents` give it its own Director and crew instead of the Know IDK Things one; the first Director is a `Lead` that adds a line for each other
  channel to the master's report). One quarterly-results video a night in Tanglish over slides. Crew: Results Scout (PLAN) → Market Analyst (DATA) → Tanglish
  Writer (SCRIPT) → Voice Clone (VOICE) → Slide Editor (EDIT) → Market Uploader (UPLOAD) → Market Analytics (REPORT, the Director's reporter); a failing member
  does not block the rest (the Uploader must still schedule what Mani approved), each idles when the job lacks the earlier part. Rules, keep them: **reported
  figures only, never advice** (`market.ADVICE` refuses it, the model's rewording is kept only if it adds no number), **a long video opens on the disclaimer
  card** (the owner's exact English and Tamil paragraphs, `market.DISCLAIMER_EN` / `DISCLAIMER_TA`, shown whole with "Mani Market Tamil" in bold, the short spoken
  line `NOTICE_SAY` unchanged; its line has `hold` 6 s, which `slides.assemble` pads the audio to) and **the description of every video on this channel ends with
  both paragraphs** (`market_crew.DISCLAIMER`), after the "Source:" lines. **A Short has no disclaimer card and no spoken disclaimer**: one small line of black
  text in Nunito Sans (`market.SHORT_NOTE`, `fonts.UI`, fetched by `python -m vision fonts`, loaded by the slide page with `@font-face` from the file, else a system
  sans) across the very top of the frame for the whole video.
  Source: NSE's integrated-filing results (`services/nse.py`: `recent` = what was filed lately market-wide, `filings`/`latest` per company), read the way a
  browser would, a few GETs a night; Screener is not used. The Scout works only between `make_after` 23:00 and `make_before` 04:00 (a manual run ignores
  that), takes one company of the index list (`index_csv`, Nifty LargeMidcap 250, kept a week in kv `mm_index`) whose newest quarter is not in kv `mm_done`
  (`SYMBOL:quarter`), makes no new video while 2 wait (BACKLOG). Voice: Mani's cloned voice (`voice/clone.py` over IndicF5, spelling rules in
  `masters/tamil_say.py`), about 22 s of work per second of speech, hence the night, and with `free_memory: true` LM Studio's model is unloaded for the
  hour and always loaded again (`services/lmstudio.py` `freed()`, via `lms ps --json`); a line the voice would garble (English letters left after
  `unspelt`) goes back to its plain wording; `voice_engine: edge` is the quick, artificial alternative. Upload is **private with no release time**, then an
  approval (kind `yt_publish`, dashboard or Telegram): approved = `videos.update` sets `publishAt` at the next slot (long videos 10:00 IST,
  `timezone: Asia/Kolkata` is honoured by `next_slot`; a channel with no `timezone` keeps the Mac's clock), rejected = it stays private (VISION never deletes a
  video). An approval decided while YouTube is signed out is remembered (`approved` on the record) and the Uploader schedules it on its next run. The Scout
  starts at 23:00 (`run_at`); one Director pass can take over an hour, and the master's lock makes the 03:00, 05:00 and six-hourly runs wait their turn, not
  overlap. **SEBI's rule (education-only creators): no price data newer than 30 days about a named stock**; the videos use filed figures only.
  **Analysis videos (a second kind of long video; Mani, 2026-10-13):** one company's fundamentals, insights only. Channel `pattern` maps the weekday of the
  RELEASE (`youtube.next_slot(fmt="long")`, in the channel's timezone) to a kind: mon/wed/fri/sat `analysis`, tue/thu/sun `topic` (a finance lesson, below; with `lessons` off a result is made
  and the Scout's summary says so; a channel with no `pattern` makes results only). The Scout takes the index member not analysed in 180 days (kv `mm_done`
  `analysis:SYMBOL`, a skipped one counts; never-analysed ones in a hash-of-release-date order, not alphabetical), plus up to 4 more for the Analyst to try when
  one has fewer than 8 ratios. Data is all primary, no Screener (its terms forbid scraping): `nse.fundamentals` sums the last four quarterly filings (eight
  consecutive ones also give the twelve months before), reads the balance sheet of the newest filing that has one (half-year or annual, opening equity from the
  filing a year earlier), the March filings' full-year context (`parse_year`; only as far back as NSE lists, from March 2025) with revenue, profit and the
  cash flow tags, and lease liabilities from the "other financial liabilities" description lines; `nse.shareholding` (promoter %), `nse.dividends`
  (`corporates-corporateActions`, per share declared in 12 months). `masters/fundamentals.py` is plain arithmetic: ROE = TTM owners' profit / average equity,
  ROCE = TTM (PBT + finance costs) / (equity + borrowings), debt = non-current + current borrowings (leases shown apart), book value = owners' equity / shares
  (paid-up / face value), EV/EBITDA with EBITDA = the operating profit above; a bank gets profit, NII, ROE, ROA, reserves, book value, promoter and valuation only.
  **Price lag (SEBI, from 1 July 2026: no named stock's price data from the preceding 30 days for an education-only creator):** `price_lag_days` (31): the price
  is the last close at or before today minus the lag, the 52-week high/low are the year ending that same day, `fundamentals.lagged` drops newer closes first, and
  the lag counts from the earlier of the Mac's date and IST's. No Yahoo answer = the price ratios are left out. The slides say the price's date and the rule, once,
  in the lines. Readings are rules of thumb stated as such (ROE 20, ROCE 20, margin 20, debt to equity 0.5 and 1.5), never a verdict: `ADVICE` also refuses
  undervalued/overvalued/cheap/expensive and their Tamil forms. Slide kind `facts` (label, value, note) was added to `slides.py`; every English word the
  voice gets is in `tamil_say.SOUNDS`. `scripts/market_analysis_sample.py SYMBOL` renders one with Edge's voice.
  **What backs a results video (Mani, 2026-10-13: more credible, "nothing is said that a source on screen does not support"):** the Market Analyst also reads
  (each optional; no piece = no slide) `nse.announcements` (`corporate-announcements`, newest first) and `filings_text.choose` takes the company's press
  release, then investor presentation, then board outcome filed within 3 days of the result (two at most, under 8 MB; `pypdf` reads the first 12 pages, a scan
  gives nothing, `relevant` keeps the sentences about figures and reasons); `nse.fundamentals` for four filing-based Key Ratios (company ROE, ROCE, debt to
  equity, net margin; bank ROE, ROA, book value; **no price ratio**, SEBI's rule), said with the analysis video's own templates; and Google News headlines
  (`news.google_news_between`, India edition, the days around the filing). The Tanglish Writer asks the model for up to 5 reasons (`market.reasons`) and **code
  keeps one only if** its quote (40+ characters) is in the document, the point is in the quote's own words (`supported`) and the quote speaks of that metric
  (`ABOUT`), every number in the point and the Tamil line is in the quote, the Tamil line has no Latin letters, no `ADVICE`/`RUDE`, and its direction equals the
  direction of our own year-on-year figure (`change`), a metric we have no figure for being dropped; at most 3 reasons (strongest move first, one a metric)
  and 1 outlook (forward-looking words, no price or target words, always introduced as "Company-ஓட guidance படி"). Slide kind `quotes` (a chip and a sentence,
  up to 4 rows) carries the reasons ("Source: Press Release, 08 Oct 2026, filed with NSE") and the news (headlines exactly as published with publication and
  date, never article text; `news_pick` keeps 3 from different publications and drops share-price, advice, preview, social and non-English headlines; a
  one-sentence Tamil gist per headline is spoken only if it passes the same checks, else the headline is shown with the template line alone). Spoken lines of
  these slides are `fixed` (the model never rewords them). The record stores `reasons` (with quote and document url), `news` and `key_ratios`; the description
  lists the filing, each company document used, each headline, then the disclaimer; the desk card has "Backed by" rows and the approval payload `backed`.
  Slide notes are Tanglish (`note_ta`) with dates as 11 Sep 2026; a margin or growth ratio always states its basis. Company names for the voice are
  `masters/names_ta.json` (all 250 index members, written by the writer model and checked to be Tamil letters only; `market.said_name`, falling back to the short
  name, which `clone.unspelt` then flags); the slides keep the written name. **ITC (2026-10-13):** revenue from operations is gross of excise duty, which the
  filing lists as a described "Excise Duty" line in other expenses (`nse.excise`, per period). Ratios now take revenue net of it where the filings list it
  (ITC operating margin 26.7 % -> 33.6 %, matching Screener's 33.6 %; FY26 vs FY25 revenue growth +10.2 % -> +4.7 %, Screener shows -3.23 %, which does not
  reconcile and is not forced); the note says "net of excise duty" or "as filed". The quarterly results table still shows revenue and margin as filed. ITC's
  FY25 profit includes about Rs 15,016 cr from the hotels demerger (discontinued operations), so profit growth FY26 vs FY25 (-40 %) is not like for like and
  its note says so (`years[].disc`).
  **Filing forms (2026-10-14):** NSE files results in five XBRL forms, told apart by the file name `INTEGRATED_FILING_<FORM>_...` (else the `IntegratedFinance_<FORM>` taxonomy
  named inside, else the tags): INDAS, BANKING, NBFC (30 index members: lenders, but also asset managers and holding companies), LI (life insurers), GI (general insurers); MCX lists none and is
  skipped quietly. `nse.parse(xml, url)` gives `kind` (indas | bank | nbfc | life | general) and `lender`; `nse.shape(x)` is how it is read: company, bank, **lender** (an NBFC whose
  interest earned is 50 % or more of its revenue: interest income, finance costs, net interest income = interest earned less finance costs (computed, key `lnii`), credit cost = impairment on
  financial instruments, profit, EPS; its quarterly filing states no stage-3 or capital-adequacy figure, so none is shown), **plain** (an NBFC-form company that does not lend: revenue, profit,
  EPS; no operating margin, no debt readings), **life** (net, first-year and renewal premium, profit = the shareholders' account's `ProfitLossAfterTax...`, not the policyholders' `NetSurplusDeficit`,
  solvency ratio, EPS) and **general** (gross premium written, net premium earned, profit, combined ratio, solvency, EPS). Lower is better: finance costs, credit cost, combined ratio. Solvency and
  combined ratio are filed as fractions and shown as percentages only inside a range a real one has (`SANE`): some filings state them scaled differently (LICI 0.0242, ICICIGI 0.0271, GICRE
  0.0432), and such a figure is left out, never rescaled. A consolidated filing is read first (insurers carry the same figures in both), the standalone one when the consolidated yields no row
  (banks always, for their NPAs). `fundamentals.ratios` by shape: lender like a bank (no ROCE, debt, margin; net interest margin left out, the filings give no earning-assets base), insurer
  (premium, profit, ROE, book value, solvency, combined ratio; shares = quarter profit / quarter EPS, no face value is filed; no ROCE, ROA, debt, margin, EV/EBITDA), EV/EBITDA for a company only;
  `fundamentals.minimum(f)` is 8 ratios for a company and 7 (`MIN_FINANCIAL`) for the others. `market`: `MEANS`/`MEANS_EN` for every new term, `KEY` key ratios per shape, `ROW_OF` maps a
  reason's metric to a form's own row, takeaways per form, `SlideEditor.title` e.g. "Premium, Profit, Solvency" / "NII, Profit, Asset Quality". **Scout coverage:** `nse.recent(c, days)` reads
  `integrated-filing-results` with `size=100` and `page=1..` (NSE honours both; a date range is ignored) until a page reaches back past `within_days` (the first page of 20 had scrolled off in
  results season); a row just filed has no `broadcast_Date`, its `creation_Date` stands in. The Scout lines up up to 3 unfinished results (`CANDIDATES`); the Analyst takes the first with rows,
  marks one without (`skip`: reason "no figures" + `parser`) and goes on, never an error (UNREADABLE only when none reads). **Retry rule:** a skip in kv `mm_done` made by an older parser
  (`nse.PARSER`, bump it when a parser change can turn "no figures" into figures; no `parser` key counts as old) is ignored (`market_crew.done_at`), so ICICIPRULI Q2 FY27 is filmed on the next
  run; the same goes for "too few ratios" analysis skips.
  **Animated slides and presenter (HyperFrames, Mani 2026-10-18; `services/hyperframes.py`, `masters/slides_motion.py`):** channel option `animated`
  (config true: Mani approved the samples, 2026-10-18). `slides.assemble(..., motion={"deck", channel, source, tag, top})` renders the whole slides track as
  one HyperFrames page timed by each line's seconds: table rows come in on their line (cells fade only: a transformed `<tr>` breaks the table), the
  spoken row is lit (rows already shown dimmed), this year's figure counts up from last year's in steps that end on the deck's own text exactly
  (`steps`, keeps commas/Indian grouping, never a figure the deck lacks; "n/a" is shown, not counted), the change chip appears after, last year and this
  year grow as bars below a table of four rows or fewer; facts count up; board cards pop; quotes slide in; cards rise and their doodles draw on; the
  disclaimer only fades in. The presenter (Mani's six tiles, `own_faces`) is in the page: mouth on the voice's loudness (`mouths`), blinks, breathing,
  a nod per line, an arm that points toward the row or card being spoken about (angle from its known place), a bounce at a good figure and a head
  tilt at a bad one; with motion the ffmpeg face overlay is skipped. Captions are still laid on by ffmpeg. Any `RenderFailed` = the still pictures,
  as before. Renderer rules: CLI pinned (`VERSION`), telemetry and update checks off, GSAP and fonts local (`python -m vision hyperframes` fetches GSAP
  into assets/hyperframes/ and Baloo Thambi 2 + JetBrains Mono into assets/fonts/), 2 workers (~3.5 GB, about half real time).
  Not done: real visemes (the tiles have 3 mouths; Rhubarb lip-sync is worth it only with 6-8 mouth drawings).
  **Pre-market and post-market Shorts (Mani, 2026-10-14; `services/world.py`, `market.report_deck/report_lines/report_react`, 1080x1920 slide kind `board`):** two
  Shorts on every NSE trading day (`world.trading_day`: Mon-Fri, not in NSE's `holiday-master` CM list, kept 7 days in kv `mm_hol`), **made from templates only, no
  model anywhere**. Pre-market is made at 07:00-08:15 IST (the run at `07:02 Asia/Kolkata`): how the US (S&P 500, Dow Jones, Nasdaq) and Europe (FTSE, DAX, CAC)
  closed, how Asia (Nikkei, Kospi, Hang Seng) is trading, where GIFT Nifty is (NSE `marketStatus`). Post-market 18:00-20:30 IST (`18:02 Asia/Kolkata`): where Nifty 50
  and Bank Nifty (NSE `allIndices`, with advances and declines) and Sensex (Yahoo) closed, how Asia closed, how Europe is trading now ("இப்போ", not closed). The
  Scout picks the job by the Indian clock (`report_window`, the Mac's Toronto clock moves with daylight saving, India's does not), once per IST date (kv `mm_done`
  `premarket:<date>`), before the night's long video; the backlog of long videos ignores Shorts. Yahoo chart (`range=5d&interval=1d`): the change is the last two
  daily closes of a closed session, or `regularMarketPrice` against the previous daily close of a live one, **never `chartPreviousClose`** (that is the close
  before the 5-day range). **Freshness is the credibility rule:** an index whose newest figure is not from the expected session (US/Europe: the last weekday before
  today IST; Asia in the morning and India, Asia, Europe in the evening: today) is left out and named (`dropped`, shown on the desk), never shown stale; no fresh
  GIFT Nifty skips the pre-market Short, no fresh Nifty or Sensex the post-market one, a region with nothing fresh is dropped, fewer than two regions = no Short
  (the Analyst says SKIPPED; nothing is marked done, so a later run in the window may try again). **Report, never predict** (SEBI's rule on recent price data): no
  line may say open/gap/expect/will/target/support/resistance/watch-a-level (`market.FORECAST`, English and Tamil, tested on every template together with `ADVICE`
  and `clone.unspelt`), no individual stock; one comic reaction from `REACT` (only those that pass the same checks) after the day's biggest move when it is 1.5 % or
  more. Every English word spoken is in `tamil_say.SOUNDS` (index names, "S&P 500" as a phrase so `&` and 500 are not read as a number). The voice is the clone or
  Edge by `voice_engine`; **LM Studio's model is unloaded only for a long video** (`free_memory` is skipped for a 40-second Short). Title "Pre-Market Update 14 Oct |
  US, Asia, GIFT Nifty என்ன சொல்லுது? #Shorts", description: what it covers, "Data: NSE, Yahoo Finance, as of <times>", then the two disclaimer paragraphs.
  **Release (`report_privacy` on the channel):** `approval` (set now) = uploaded private + the usual `yt_publish` approval; `scheduled` = published with NO review
  (held back only when a data or voice check fails; the owner has not decided). Either way `youtube.report_release`: pre-market 15 minutes after it is ready or
  approved, only if that is before 09:10 IST that date, else **stale** (stays private, record status `stale`, desk stage "Stale · not published", never published
  by approval); post-market 21:00 IST that day if still ahead, else 15 minutes on while still that Indian date, else stale. Reports never take a slot from
  `next_slot`, so the long video's 10:00 stays free.
  **Zoned `run_at`:** a master's `run_at` entry may carry a zone, `"07:02 Asia/Kolkata"` (`orchestrator.run_time`; a bare `"05:00"` is still the Mac's clock). The
  youtube master runs ALL its channels at those times (Know IDK Things's own limits, `create_after` and per-day counts, still apply).
  **Wording fixed, English captions, sign-offs (Mani, 2026-10-14; he approved the HDFC video's Tanglish by ear):** the template wording is final, so the Tanglish
  Writer calls `market.reword` only when the channel option `reword` is true (default and config: false; the model still writes the verified reasons and headline gists, which
  are `fixed`). **Every video and Short has English translated captions burned in** (channel option `captions`, config true): code writes them, no model. Each
  spoken line dict carries `"en"` beside `"say"`, built by an English twin of every template (`_row_en`, `_fact_en`, `MEANS_EN`, `TELL_EN`, `REACT_EN`, takeaways, report
  lines; reasons = the English lead-in + the verified `point`, headlines = the lead-in + the headline as published). Figures are read for reading (`fig_en`: ₹73,188 crore,
  11.2%, ₹38.37); `tests/test_captions.py` checks that every line of every deck shape has an `en` whose numbers (`market.numbers`) equal the spoken line's, and that no
  `en` matches `ADVICE`/`RUDE`/`FORECAST` (the company's own words and headlines on a `quotes` slide are exempt from FORECAST, and their numbers need only include the
  spoken ones). A line with no `en` simply shows no caption. In `slides.py`: `caption_chunks` cuts a caption at sentence ends and commas first, then evenly at word breaks
  (wide ~60 characters / 10 words, tall ~32 / 6; a number never parts from its unit), `caption_times` shares the line's spoken seconds by character count and gives its pause
  (and the notice's hold) to the last chunk, so nothing shows across a line boundary; `pictures(..., captions=texts)` draws each distinct chunk once in the same Chrome
  session as a transparent strip the width of the frame (dark band `#1b1b1b` at 85 %, white Nunito Sans 600, 40 px wide / 46 px tall; `CAP` holds the placement: wide
  video above the channel mark and left of the presenter, Short above YouTube's bottom 280 px and left of the right 120 px) and returns it as a third value; `assemble(...,
  captions={"plan", "pngs"})` overlays them with one more concat input and writes `captions.srt` beside `final.mp4` (not uploaded; for a subtitle track later). Without
  `captions` the pipeline is unchanged; test fakes that return `(pngs, faces)` just get no captions. **Two fixed sign-offs** (`market.SUBSCRIBE_LONG`, `SUBSCRIBE_SHORT`,
  never reworded): a long video says SUBSCRIBE_LONG as its very last line after the unchanged closing line (same slide, no new slide); a Short's last line is
  SUBSCRIBE_SHORT (it replaced the old "analysis-க்கு" line; `SIGN_OFF` is kept as an alias). Their words are in `tamil_say.SOUNDS` (bell icon, click, notification, "time-க்கு"
  as டைமுக்கு, market and finance, ...). `tamil_say._join` now glides with ய after a front vowel sign (ி ீ ெ ே ை: டெய்லி-உம் -> டெய்லியும்) and வ elsewhere; the 13 golden
  lines in `tests/test_voice.py` come out unchanged. The sample scripts render captions by default (`--no-captions`), use the template wording (`--reword` opts in to the
  model; `--plain` is accepted and does nothing) and take `--mani` for the cloned voice (suffix `-mani`); the English line is printed under each spoken line in the .txt.
  Not built yet: news Shorts for non-trading days, SEO for this channel, and the presenter drawn from
  Mani's own character art (now a stand-in drawing). `publish_times` in the channel's options is unused. A live Europe session in the post-market Short has only
  been tested on made-up data (the sample was run in the morning); sample: `scripts/market_report_sample.py premarket|postmarket [--any-time] [--date D]`.
  Edge's voice function is `market_crew.edge_speak`; the sample scripts in `scripts/` are for trying looks and voices by hand.
  **Voice fixes (`tamil_say.fixes/set_fix/source`, `data/voice_fixes.json`, git-ignored):** Mani's own spellings `{lower-case English word or phrase: Tamil letters}`, applied by
  `voiced` BEFORE `SOUNDS` and the learned table (his word wins; longest match first, whole words, case ignored; the "ch" rule is not applied to his spelling). Set by Telegram
  `/say word = ச்சேனல்` (`/say word` shows the spelling and where it comes from; only from TELEGRAM_CHAT_ID) or `POST /api/voice/fix`. A word that is in a line of the approved HDFC
  reference (`tests/golden_voice.json`) is refused ("change it there first") unless `force` / `/say!`; the golden file is never changed by it, so `tests/test_voice.py` fails
  until the reference is re-recorded (the reply says so and it is logged). No dashboard control (the desk's "New words" row has only the API).
  **Covers and titles for long videos (`masters/thumbs.py`, `services/logos.py`, `slides.thumb_page/thumbnail`, `scripts/market_thumb_sample.py`):** the Slide Editor makes `thumb.jpg`
  (1280x720, under 2 MB, headless Chrome like the slides: paper, green pill, Baloo/Tamil type, the presenter bottom right) for results, analysis and lessons (a Short has none; YouTube
  gives it no use). The 2-5 word Tanglish hook is picked by code from the video's own figures (profit up/down/same against last year, else the headline figure; an analysis's ROE as a
  question; a lesson's subject: "FD vs RD: எது?"), every hook and title through `thumbs.clean` (ADVICE, FORECAST, RUDE, `youtube.promises`, 100 characters). Result title: "TCS Q2 FY27
  Results | Profit 15% ஏறிருக்கு, Margin ஏன் இறங்குச்சு? | தமிழில்" (the margin question only when profit rose and margin fell; without it if too long; no figures = the old title).
  A company's logo comes from Wikimedia Commons' API (`logos.find`, GET, 1 s apart, a User-Agent that names VISION or Commons answers 403): a file only if its title has every
  significant word of the company's name and "logo", SVG or PNG, not "old/former/dated"; cached in `data/logos/<SYMBOL>.<ext>` + `.json` (licence, artist, source page), never fetched
  again, no match remembered 30 days. It sits in a small white card; the channel's look dominates. The description lists "Logo: <Commons page> (<licence>)" before the disclaimer; the
  record has `thumb` and `logo`. `youtube.set_thumbnail` is called by the Market Uploader right after a long upload (it never called `_extras` before, so no cover was ever set); a
  refusal is a note. The approval payload now also carries `watch` (youtu.be link), `video` (the record's kind), `new_words` (learned words used, for results too) and `sources`.
  **Learning from views (`market_crew.learn`, `by_own_views`):** Market Analytics writes kv `yt_state` `manimarket:insights`: average views a day since going public (publish time,
  else upload time) over public videos older than 2 days, per kind (result, analysis, lesson, premarket, postmarket, lesson_short) and per lesson topic group, and the top kind (shown
  in the channel's report line). Nothing changes until 8 such videos of a kind exist; then, where the owner's pattern leaves a choice, the lesson topic: `youtube.choose` over the groups
  (more views a day first, `LEARN_EXPLORE` 0.2 held to 70 %/groups for the rest, told counts from the log) puts that group's topics first (inside a group the signal/least-recent order
  stands). Which company kind is analysed is NOT affected (weekday pattern, 180-day rule).
  **Finance lessons (Mani, 2026-10-14; `masters/lessons.py`, `services/yt_channels.py`, `services/yt_transcripts.py`; options `lessons`, `lesson_shorts`, `lesson_channels`,
  `transcripts_per_day`):** on a `topic` release day (tue, thu, sun) the Scout lines up a lesson in place of a result (the night's first result stays as the fallback if no lesson can
  be made: all sources dead, no writer); on a day the market is shut (Sat, Sun, an NSE holiday) the two Short windows (07:00-08:15 and 18:00-20:30 IST) make a lesson Short in place of the
  pre/post-market one (kind `lesson_short`; once per window per date, kv `mm_done` `lesson_short:<window>:<date>`; released 09:00 and 21:00 IST by `youtube.lesson_release`, stale = stays
  private once its Indian date is over). **A lesson and a lesson Short are model-written, so they ALWAYS go through the approval gate, whatever `privacy`/`report_privacy` say**
  (`youtube.LESSON_KINDS` are uploaded private and never given a `publishAt` or a `next_slot`). Subjects: the topic bank `lessons.TOPICS` (about 45: FDs/RDs, mutual funds, bonds and G-Secs,
  SGBs and gold, PPF/SSY/NPS, term vs ULIP, tax regimes/80C/capital gains, credit score, budgeting, compounding, inflation, F&O risk from SEBI's study, IPOs, demat, LRS/GIFT City...), each with
  1-4 official pages (RBI, SEBI, DICGC, India Post, AMFI, Income Tax, PFRDA/NPS Trust, IRDAI, IFSCA, NCFE); **never an individual stock or the market's direction**. Order
  (`lessons.rank`): topics that top Indian finance channels' recent videos are getting views for first (`lesson_channels` names, resolved once with `search.list` at 100 quota units each and
  kept for ever in kv `mm_state`; then one cheap read a day: uploads page, `videos.list` statistics; whole-word match of a title to the topic's search words; score = recent views per day;
  auth = `YOUTUBE_API_KEY` if set, else the channel's own sign-in, none = no signals), the rest least recently made first; a topic is not repeated within 180 days (kv `mm_done`
  `lesson:<id>`; a Short topic: at most 3 concepts, 30 days apart, `lessonshort:<id>`); a topic with no usable page (`NO SOURCE`) or too few good lines (`TOO THIN`) is left alone 3 days
  (`lessonskip:<id>`) and the next is tried, two topics a night at most. **Written in two steps (2026-10-14; the first version asked the model for Tamil letters directly and nearly every line was refused or came out as book Tamil).** Step A, English (`lesson_model`
or the usual writer): one request returns the title, the slides (English) and 18-22 English lines `{slide, show, en, quotes}`; a second request replaces lines the checks threw out (only if under 14 survive; a Short 5).
**Facts come only from the official pages fetched that night, checked by code in English** (`lessons.check_en`): every quote (30+ characters) is found in a page, every number in `en` is in the
quotes, `en` is *backed* by them (`backed_by`: 60 % of its longer words, by stem, in one quote; a line that names FD/RD/NPS... by its acronym is held clause by clause, so two quotes cannot be
stitched into a claim neither makes), no ADVICE, FORECAST or RUDE wording, no company in the index (name, symbol, well-known bank), no Nifty/Sensex/rally/bull/bear/share-price wording, no run of 8 words
shared with a transcript, no near-repeat; a quote is matched ignoring a parenthetical and the rupee's spelling (`squash`), Indian amounts compare as figures (`figs`), and every slide item must be held
by a sentence of the pages (`item_backed`). The verified `en` is the burned-in caption, exactly. Step B, Tanglish (`lesson_tamil_model`, default `qwen/qwen3.8-27b`, which has its own Groq daily
allowance; if it cannot answer, the writer model is asked): ONE request with all verified English lines (`TANGLISH`: host of a Tamil finance channel, colloquial Chennai speech, the golden lines of
`tests/golden_voice.json` as the register, a spoken-vs-written list, English finance words left in English letters). Code keeps a spoken line only if (`check_ta`) it has exactly the English line's
digits (`market.numbers`; "5 லட்சம்" or "5,00,000" for "5 lakh" is refused, the voice turns digits into words), has Tamil in it, no ADVICE/FORECAST/RUDE, no company or market, and no **book-Tamil marker**
(`BOOKISH`: உள்ளது, உள்ளன, செய்யலாம், செய்ய வேண்டும், ஆகையால், எனவே, மேலும், ஆனால், மாதம், செலுத்த, அநுசாரி/அனுசாரி, ஆகும், போன்ற, மற்றும், என்பது, நீங்கள்...; the short ones only as whole words, so மாசம் and ஆனா
pass; `tests/test_lessons.py` checks that no golden line matches). Refused lines go back ONCE in a second request with the reason for each; still refused = the line is dropped, caption and all.
**Words for the voice:** English words left in a kept line must be speakable by the cloned voice. Those not in `tamil_say.SOUNDS` are learned: a few lesson words and acronyms (letter by letter) from
code (`WORDS_TA`, `seeds`), the rest from one small request asking how a Tamil speaker says each; a value is accepted only if it is Tamil letters, never overwrites an entry, never shadows `SOUNDS`
(`tamil_say.learn`; a word starting with the "ch" sound is spelt ச்ச..., because a bare ச is read as "s" (the voice said "senal"): the prompt says so and `ch_sound` enforces it, `SOUNDS["channel"]` is ச்சேனல்; file `data/voice_words.json`, git-ignored, read by `voiced` as a second table after SOUNDS). A line with a word still unsayable is dropped. **Mani checks the learned words by ear**:
they are listed on the desk card ("New words for the voice"), in the approval payload and in the record (`new_words`); correct one by editing the file (or move it into SOUNDS). The golden lines are
unaffected by design (tested). Fewer than 10 spoken lines kept (a Short: 4) = TOO THIN. The slides show only items without invented numbers, each with its "Source: <page> ·
<domain>" chip. Dropped lines are logged with the reason and counted on the record. Requests stay small for Groq's per-minute allowances (a lesson: about 7,000 tokens for step A, 5,000 for step B; see the
2026-10-14 samples below). **Groq's free day is 200,000 tokens PER MODEL, shared with every other writer in VISION** (on 2026-10-14 `openai/gpt-oss-120b` stood at 198,000 used and refused every request):
a 429 in either step is `WRITER BUSY` (the topic is NOT skipped, the next run tries again); `lesson_model` names another Groq model for step A. Qwen3 on Groq needs `reasoning_effort: none` (`llm.py`
sets it; "low" leaves it thinking with an empty answer), and its output-tokens-a-minute limit can answer 429 to a big request: `llm.py` waits and retries.
The long lesson opens on the disclaimer card as ever, has a fixed opening line, a fixed closing ("This is only an educational lesson...") and SUBSCRIBE_LONG; the Short has the small
  top line, no spoken disclaimer, and ends on SUBSCRIBE_SHORT. The description is "what it covers", hashtags, "Sources:" (each page's name and address) and the two disclaimer paragraphs.
  **Transcripts (Mani's own call, 2026-10-14, against YouTube's terms of service, on the same footing as the LinkedIn call):** the public transcripts of the most-viewed videos that matched
  the chosen topic are read as raw material for the topic, the angle, viewers' questions and common misunderstandings, **never for wording and never as a source of facts**. Limits in code,
  keep them: no cookies, no sign-in, no proxy (the `youtube-transcript-api` package's defaults); at most `transcripts_per_day` (10) videos a day, 5 s apart; any block (RequestBlocked,
  IpBlocked, TooManyRequests, a 429) stops transcript reading for the rest of the day (kv `mm_state` `transcripts`) with no retry; a video without one is skipped. Before Groq sees a word
  the code removes every sentence that names a company in the index (or a well-known bank or broker), speaks of share price, target, buying, selling, multibagger, the market's direction,
  or matches ADVICE/FORECAST, and caps it at ~2,500 tokens; the angle it returns may hold no number. The videos read are recorded (`inspired`: title, channel, link) on the record, the
  approval and the desk, and appear nowhere in the video or its description. Sample: `scripts/market_lesson_sample.py <topic id> [--short] [--videos ID,ID]` (Edge's voice only).

## Status
| Master | Mode | Needs from Mani |
|---|---|---|
| Investments | live | Kite login link, FYERS_APP_ID/SECRET (+PIN), Wealthsimple CSV in inbox/wealthsimple |
| Email / Calendar | live | GOOGLE_CLIENT_ID/SECRET and/or MS_CLIENT_ID/SECRET, accounts in config, sign-in |
| Job Hunt | live | resumes in vault/resume (done), target companies (optional); Adzuna is paid and switched off |
| Web Designer | live | GOOGLE_MAPS_API_KEY, CLOUDFLARE_API_TOKEN + ACCOUNT_ID, optional PEXELS_API_KEY / PIXABAY_API_KEY |
| World Watch (news, weather, flights, traffic) | live | TOMTOM_API_KEY for traffic; optional OPENSKY creds (a free account lifts flights from about 100 to 1,000 snapshots a day) |
| Trading Desk | live | OANDA practice token + account |
| YouTube Manager (+ Mani Market Tamil) | live (upload mocked only, never run against YouTube) | GROQ_API_KEY, PEXELS_API_KEY (the .env line has no usable value), REDDIT_CLIENT_ID/SECRET or .txt stories in inbox/stories/knowidk; GOOGLE_CLIENT_ID/SECRET with YouTube Data API v3 and Google Drive API enabled and redirect `http://127.0.0.1:8765/auth/youtube/callback`, then the YouTube sign-in. Mani Market Tamil: its own YouTube sign-in (`/auth/youtube/login?account=youtube-manimarket`), `vault/voice/ref-tight.wav` + `ref.txt` and the IndicF5 model for the cloned voice, headless Chrome (selenium) for the slides, LM Studio's `lms` tool |
| E-books Manager | live (never run for real yet) | CLOUDFLARE_API_TOKEN with Workers AI + CLOUDFLARE_ACCOUNT_ID (set), GROQ_API_KEY; uploads each approved book to KDP by hand |
| Visa Watch | live (never run signed in) | add the account on its desk, then sign in to the portal himself in the window it opens (again whenever the session runs out); the Keychain prompt allowed once |
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
6. YouTube Manager: first real upload done 2026-10-05 (Drive → Short → unlisted, counted as a Short). Open: Mani tuning the
   mood → voice table by ear (samples in `data/shorts/_voices/`), collecting stories from comments on the channel's own videos,
   crew progress in vision.log.

Canvas design of the dashboard: https://claude.ai/artifact/46JvfVBsfsbd5f8FSqaYVf
