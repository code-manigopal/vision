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
  agents.py        SubAgent / StubAgent / Stage / Master; Director (a sub-agent with its own crew); request_approval(ctx, ...)
  orchestrator.py  boot roll call, per-master schedules, 06:00/18:00 briefs, reminders (minutely),
                   approval actions (watches approval_decided -> APPROVAL_HANDLERS[kind])
  server.py        FastAPI: dashboard, /ws, /api/*, OAuth + Fyers login callbacks
  ask.py           AskEngine: LLM tool-calling over master data; session memory 30 min
  voice/           TTS (kokoro | piper | macos), STT (mlx-whisper), WakeWord (openWakeWord)
  channels/telegram.py   briefs, alerts, reminders, notices, /commands, approve/reject buttons
  services/        llm.py (LM Studio OpenAI-compatible + Anthropic + a hosted "writer" tier on Groq), oauth.py (Google/Microsoft),
                   reddit.py (official API, read-only), gdrive.py (Drive folder, read-only), bgm.py (music library from Openverse), gutenberg.py (public-domain story books), stock_video.py (Pexels/Pixabay footage), genmedia.py (AI footage provider slot),
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
   traffic=Incident Scout, youtube=Confessions Everywhere Director (its crew reports to it through Analytics Manager).
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
· `GET /api/issues` · `POST /api/issues/explain {master, agent}` → `{text, source}` · `GET /api/approvals/{id}/email` (full body + attachments) · `GET /api/approvals/{id}/attachments/{att}` (streamed, never stored)
· `GET /api/desk/{master}` (read-only pipeline: stages + items + artifacts) · `GET /api/files/{path}` (only `data/sites`, `data/applications`)
· `POST /api/tts {text, voice?}` → wav · `GET /api/voices` (Kokoro's English voices) · `POST /api/stt` (raw audio body) → `{text}` · `GET /api/traffic?city=` · `GET /api/weather/grid` (globe weather, ~100 points, cached 1 h)
· `/auth/{google|microsoft|youtube}/login?account=` + `/callback` · `/auth/fyers/login` + `/callback` · `WS /ws`

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
  card at a time (`startBrief` / `deckSpeak`); clicking a red agent or asking "what's wrong" opens issue cards and VISION
  explains via `/api/issues/explain`. Tilt, scan lines and tint are switches in the voice menu (`vision-holo`).
  Mode `decide` is the decision deck: one wide card per approval (Review button, or "show my decisions"); an email reply
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
- Trading: practice account default; live needs OANDA_ENV=live AND options.live_trading: true;
  approval TTL 30 min; refuse if price moved > 0.5 ATR; units capped.
- Weather Agent belongs to News Desk; World Watch is flights only (the globe's weather icons are a plain data endpoint, not an agent).
  World Watch shows `near_slots` (10) flights nearest home first, the rest spread worldwide; a route lookup is spent only on callsigns not yet known.
- Traffic Desk is read-only (no approval gate).
- YouTube Manager (`masters/youtube.py`, took the Film Studio slot) has three levels: master → one Director per channel
  (`options.channels`) → that channel's crew. `Director` (agents.py) runs its crew like a master runs sub-agents; crew
  agent events carry `director`. Crew for Confessions Everywhere: Story Scout → Story Writer → Screenplay Writer →
  Keyword Generator + Voice Artist + SEO Strategist → Footage Collector → Footage Generator → Editor → Uploader → Analytics Manager.
  **Mani's choice (2026-10-06): no review at all for Confessions Everywhere.** `privacy: scheduled` uploads each Short as
  private with a publishing time: the first `publish_times` slot after the last release already scheduled (`next_slot`;
  the releases are one queue in upload order, never filled into an earlier gap; the Uploader first refreshes every
  video's `publishAt` so Mani's hand-set times count), and YouTube makes it public by
  itself; no notice is raised. His rhythm: four a day, released at 06:00, 12:00, 18:00 and 00:00. The master runs every morning
  at 05:00 (`run_at` on the master, a cron job beside the six-hourly cycle) to make, upload and schedule the day's four;
  `create_after: "05:00"` keeps a night-time cycle from starting the day's Shorts early. (`privacy: unlisted` is the earlier mode: a notice with the Studio link, public or delete by
  hand.) A private video with a `publishAt` counts as `scheduled`, whether VISION or Mani scheduled it. Analytics Manager checks each uploaded Short
  (status, views, likes, comments), clears the notice once it is public or deleted, and its report feeds the briefs.
  Sign-in per channel: `/auth/youtube/login?account=youtube-<channel id>` (oauth provider `youtube`, same Google app).
  Stories come from `inbox/confessions/<channel id>/*.txt` (first line may be the source URL); the Scout first copies new
  Docs and .txt files from the channel's Google Drive folder (`drive_folder`, `services/gdrive.py`, read-only, same sign-in
  as YouTube, fetched ids in kv `yt_drive`) into that inbox. Reddit's official API is wired in but asleep: Reddit now makes
  new accounts register for API access before an app can be created, and a monetised channel may be refused;
  **Quora is out** (no API). With `originals: true`, when no real story is waiting the Scout takes a premise from its bank
  (kv `yt_premises`; refilled in batches by the model from code-picked ingredients THEMES x SETTINGS x TELLERS x TURNS, each
  premise used once, near-duplicates dropped) and the Writer writes an original, fictional confession-style story: never
  framed as real or as "someone shared", marked `original` in the log, "This story is fiction." in the description.
  Other sources, in the Scout's order: long comments under the channel's own Shorts (`viewer_comments`, kind `viewer`) →
  Drive/inbox/Reddit → one classic a day (`classics`: Project Gutenberg book ids, `services/gutenberg.py` cuts a book at its
  capitalised headings into `data/classics/<id>/`; retold faithfully with the author's ending, citation spoken as the last
  line and in the description; used stories in kv `yt_classics`) → originals. Every Short carries the invitation to leave a
  confession: the spoken `outro`, the `cta` line in the description and the channel's own comment (the API cannot pin it;
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
  Originals come in kinds that take turns (`original_genres`): confession, motivational, and science (48 subjects across
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
  **Quick Shorts** (`quick`, `QUICK`: 20-35 s, ends on its own outro, `per_day` 1, 0 = off): only an original story can be one (Scout sets
  `job["quick"]`), counted among the day's Shorts; `word_range(ch, quick=True)`; insights keep `views_by_length` (quick vs regular).
  **Double down** (`double_down`, `double_down_after` 12, `explore` 0.15): `choose(options, told, views, floor)` gives each option a floor share
  and the rest by average views; the Scout uses it for the original kind (`views_by_kind`, a confession counts as "original") and the learning
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
  credits), seen stories in kv `yt_seen`. Footage Generator is a provider slot (`services/genmedia.py`, `generator:` per
  channel), off until a provider is named. Writing uses `llm.writer_model` on Groq (reasoning models need large max_tokens).

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
| YouTube Manager | live (upload mocked only, never run against YouTube) | GROQ_API_KEY, PEXELS_API_KEY (the .env line has no usable value), REDDIT_CLIENT_ID/SECRET or .txt stories in inbox/confessions/confessions; GOOGLE_CLIENT_ID/SECRET with YouTube Data API v3 and Google Drive API enabled and redirect `http://127.0.0.1:8765/auth/youtube/callback`, then the YouTube sign-in |
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
   mood → voice table by ear (samples in `data/shorts/_voices/`), collecting confessions from comments on the channel's own videos,
   crew progress in vision.log.

Canvas design of the dashboard: https://claude.ai/artifact/46JvfVBsfsbd5f8FSqaYVf
