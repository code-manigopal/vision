// Runs the dashboard's logic (no browser) for every view, connected and not:  node tests/dashboard_smoke.mjs
// Fails on a crash, or on sample values showing while connected.
import fs from 'node:fs';
const html = fs.readFileSync(new URL('../dashboard/Main.dc.html', import.meta.url), 'utf8');
const src = html.match(/<script type="text\/x-dc" data-dc-script[^>]*>([\s\S]*?)<\/script>/)[1];
globalThis.window = { location: { hostname: 'localhost', host: 'localhost:8765', protocol: 'http:' }, localStorage: { getItem: () => null, setItem() {} }, addEventListener() {} };
globalThis.document = {}; globalThis.location = window.location;
globalThis.fetch = async () => ({ ok: true, json: async () => ({ text: 'The key is missing. Add it to the settings file.' }) });
class DCLogic { constructor(p) { this.props = p; } setState(p) { Object.assign(this.state, p); } }
const Component = new Function('DCLogic', src + '\nreturn Component;')(DCLogic);
const live = {
  empty: { masters: {}, reports: {}, report_data: {}, notices: {}, approvals: [], boot: { active: false, done: 0, total: 0 }, telegram: { connected: false }, voice: {} },
  full: { masters: { news: { agents: [{ name: 'News Summarizer', status: 'done', label: '5 ITEMS', summary: '4 desks updated' }] },
      traffic: { agents: [{ name: 'City Geocoder', status: 'error', label: 'ERROR', summary: 'Add TOMTOM_API_KEY to .env' }, { name: 'Traffic Poller', status: 'idle', label: 'BLOCKED', summary: 'Waiting on City Geocoder' }] } },
    reports: { news: '4 desks updated', invest: 'Portfolio −C$227' },
    report_data: { invest: { ports: [{ name: 'Total (CAD)', value: -227, pct: -1.32, sym: 'C$', total: true }], mkts: [{ name: 'NIFTY 50', pct: -0.88 }, { name: 'Bitcoin (24h)', pct: null }] },
      news: { headlines: [{ tag: 'GLOBAL', text: 'A headline', source: 'CNBC' }], weather: { city: 'Leamington', temp: 20, words: 'cloudy', kind: 'cloud', daily: [{ kind: 'cloud', hi: 21 }] } },
      calendar: { events: [{ title: 'Standup', start: new Date().toISOString(), all_day: false }] }, world: { flights: [], total_airborne: 0 } },
    notices: { kite: { text: 'Zerodha login needed', url: 'http://x' } }, approvals: [{ id: 1, master: 'web', title: 'Pitch to X · demo https://demo-x.workers.dev' }],
    boot: { active: false, done: 66, total: 66 }, telegram: { connected: true }, voice: {}, system: [{ id: 'cpu', label: 'CPU', pct: 10, hot: 80, detail: '' }] } };
const SAMPLES = ['Episode 04', '28 flights', '1,840', 'Team standup', 'DEMO DATA', 'steps · avg', 'reminder 15 min', 'OANDA mismatch', '22 and cloudy', '7:00'];
let fails = 0; const seen = new Set();
const fail = (...a) => { fails++; console.log(...a); };
const mk = (st) => { const c = new Component({}); Object.assign(c.state, { log: [], boot: false }, st); c.scrollToTop = () => {}; return c; };
for (const [name, L] of [['preview', null], ['connected-empty', live.empty], ['connected-full', live.full]])
  for (const mode of ['ambient', 'briefing', 'issues', 'calendar', 'world', 'ask']) for (const master of ['trading', 'traffic', 'film']) {
    const c = mk({ mode, master, liveUp: !!L, live: L, askSrc: 'offline', askSteps: [['VISION', 'A', 'b', '']], askChips: ['X'], askQ: 'q', askSay: 's', askAt: Date.now() - 5000, askFollow: [] });
    let v; try { v = c.renderVals(); } catch (e) { fail('CRASH', name, mode, master, String(e).slice(0, 200)); continue; }
    if (L) for (const key of Object.keys(v)) { const txt = JSON.stringify(v[key], (k, x) => typeof x === 'function' ? undefined : x) || '';
      for (const bad of SAMPLES) if (txt.includes(bad) && !seen.has(key + bad)) { seen.add(key + bad); fail('SAMPLE VALUE', name, mode, key, JSON.stringify(bad)); } }
  }
// the card deck: briefing narrates card by card; arrows step; issues explain the failing agent
const said = []; const c = mk({ liveUp: true, live: live.full });
c.speak = (t, after) => { said.push(t); c._after = after; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
c.renderVals(); c.startBrief(); await wait(800); let v = c.renderVals();
if (c.state.mode !== 'briefing' || !v.deckOn || v.deckCards.length < 5) fail('deck did not open', c.state.mode, v.deckCards.length);
if (v.deckCards.filter((x) => x.center).length !== 1 || !v.deckCards[0].center) fail('first card should be the centre one');
c._after(); await wait(600); v = c.renderVals();                       // speech ended -> advances and reads the next card
if (c.state.deckI !== 1 || said.length !== 2) fail('voice did not advance the deck', c.state.deckI, said.length);
c.deckGo(2); await wait(120); v = c.renderVals();                      // arrow keys jump and VISION picks up there
if (c.state.deckI !== 3 || !v.deckCards[3].center || said.length !== 3) fail('arrow step failed', c.state.deckI, said.length);
c.deckToggle(); if (c.state.deckTalk) fail('pause did not stop narration');
c.openIssues('traffic/City Geocoder'); c.renderVals(); await wait(200); v = c.renderVals();   // the real runtime re-renders on setState
const ic = v.deckCards.find((x) => x.center);
if (c.state.mode !== 'issues' || !ic || ic.title !== 'City Geocoder' || !/Traffic Poller/.test(JSON.stringify(ic.rows))) fail('issue card wrong', JSON.stringify(ic && [ic.title, ic.rows]));
if (!/key is missing/.test(said[said.length - 1]) || !/key is missing/.test(ic.body)) fail('issue was not explained', said[said.length - 1], ic && ic.body, JSON.stringify(c.state.issueText));
const p = mk({ liveUp: true, live: live.full, master: 'traffic' }).renderVals();
if (p.agents[0].cursor !== 'pointer' || p.agents[1].cursor !== 'default') fail('failing agent row should be clickable');
const lv = mk({ listening: true }).renderVals();
if (lv.listenRing !== 'lring-on' || lv.statusMsg !== 'Listening…' || !/listen/.test(lv.coreImgCls)) fail('listening mode is not shown on the core');
// "Hey Vision": a fake recogniser feeds phrases; only the wake phrase wakes it, and a command in the same breath runs
class FakeSR { start() { FakeSR.last = this; } abort() { this.aborted = true; } }
window.webkitSpeechRecognition = FakeSR;
const w = mk({ wakeOn: true, liveUp: false }); const ran = []; let listened = 0;
w.runCommand = (x) => ran.push(x); w.listenLocal = () => { listened++; }; w.say = () => {};
const hear = (text, isFinal) => FakeSR.last.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: text }], { isFinal })] });
w.wakeStart(); if (!w.state.wakeLive) fail('wake listener did not start');
hear('what a nice television', true); if (ran.length || w.state.wakeHeard) fail('woke on the wrong words');
hear('hey vision', false); if (!w.state.wakeHeard || w.renderVals().listenRing !== 'lring-on') fail('core did not show it heard the wake phrase');
hear('hey vision brief me', true); if (ran[0] !== 'brief me' || w.wakeRec) fail('command in the same breath was not run', JSON.stringify(ran));
w.wakeStart(); const sr2 = FakeSR.last; w.startVoice = () => { listened++; }; hear('Hey, Vision.', true);
if (listened !== 1 || !sr2.aborted) fail('bare wake phrase should open the mic and stop the wake listener', listened);
console.log('spoken:', said.map((x) => x.slice(0, 70)));
console.log(fails ? fails + ' problem(s)' : 'dashboard logic OK: no crashes, no sample values while connected, deck works');
process.exit(fails ? 1 : 0);
