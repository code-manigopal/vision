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
    notices: { kite: { text: 'Zerodha login needed', url: 'http://x' } }, approvals: [{ id: 1, master: 'web', title: 'Pitch to X · demo https://demo-x.workers.dev', payload: { kind: 'proposal', message: 'Hi X team', url: 'https://demo-x.workers.dev', phone: '519 555 0100' } },
      { id: 2, master: 'email', title: 'Reply to Anna: Meeting', payload: { kind: 'email_reply', draft: 'p:1' } },
      { id: 3, master: 'trading', title: 'Sell 352 EUR/USD @ ~1.12864', payload: { kind: 'trade', instrument: 'EUR_USD', units: -352, price: 1.12864, stop: 1.13258, tp: 1.12339, rating: 'Underweight', reason: 'Momentum is fading.', created: Date.now() / 1000 - 600 } },
      { id: 4, master: 'calendar', title: 'Meeting with Anna: Thu', payload: { kind: 'meeting_accept', start: '2026-10-08T14:00:00', end: '2026-10-08T14:30:00', attendees: ['anna@x.com'], account: 'personal', email: { subject: 'Meet?', snippet: 'Can we meet' } } },
      { id: 5, master: 'jobs', title: 'Application package: Analyst @ Acme (fit 82)', payload: { kind: 'job_package', url: 'https://jobs/1', folder: 'data/applications/acme' } }],
    boot: { active: false, done: 66, total: 66 }, telegram: { connected: true }, voice: {}, system: [{ id: 'cpu', label: 'CPU', pct: 10, hot: 80, detail: '' }] } };
const SAMPLES = ['Episode 04', '28 flights', '1,840', 'Team standup', 'DEMO DATA', 'steps · avg', 'reminder 15 min', 'OANDA mismatch', '22 and cloudy', '7:00'];
let fails = 0; const seen = new Set();
const fail = (...a) => { fails++; console.log(...a); };
const mk = (st) => { const c = new Component({}); Object.assign(c.state, { log: [], boot: false }, st); c.scrollToTop = () => {}; return c; };
for (const [name, L] of [['preview', null], ['connected-empty', live.empty], ['connected-full', live.full]])
  for (const mode of ['ambient', 'briefing', 'issues', 'decide', 'desk', 'calendar', 'world', 'ask']) for (const master of ['trading', 'traffic', 'film']) {
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
// decision deck: every approval is a card; the email card shows the original, the draft and its attachments
const posts = [];
globalThis.fetch = async (url, opt) => { if (opt && opt.method === 'POST') { posts.push(url); return { ok: true, json: async () => ({}) }; }
  return { ok: true, json: async () => ({ email: { from_name: 'Anna Lee', from: 'anna@x.com', subject: 'Meeting next week', ts: 1790000000, body: 'Could we meet Thursday?' }, draft: { to: 'anna@x.com', subject: 'Re: Meeting next week', body: 'Thursday works.' },
    attachments: [{ id: 'a1', name: 'agenda.pdf', mime: 'application/pdf', size: 204800 }, { id: 'a2', name: 'notes.docx', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', size: 9000 }] }) }; };
const dq = mk({ liveUp: true, live: live.full }); dq.speak = () => {};
dq.renderVals(); dq.openDecide(2); dq.renderVals(); await wait(150); let dv = dq.renderVals(); await wait(30); dv = dq.renderVals();
let dc = dv.deckCards.find((x) => x.center);
if (dq.state.mode !== 'decide' || dv.deckCards.length !== 5 || !dc || !dc.showMail) fail('email decision card did not load the original', dq.state.mode, dv.deckCards.length, dc && dc.title);
else {
  if (!/Anna Lee/.test(dc.mailHead) || !/Thursday\?/.test(dc.mailBody) || !/Thursday works/.test(dc.draftBody)) fail('email card content wrong');
  if (dc.atts.length !== 2 || !/agenda\.pdf · 200 KB/.test(dc.atts[0].label)) fail('attachments not listed', JSON.stringify(dc.atts.map((x) => x.label)));
  dc.atts[0].open(); dc = dq.renderVals().deckCards.find((x) => x.center);
  if (!dc.showPrev || !dc.prevPdf || dc.prevSrc !== '/api/approvals/2/attachments/a1' || dc.showMail) fail('pdf attachment preview wrong');
  dc.prevClose(); dq.renderVals().deckCards.find((x) => x.center).atts[1].open(); dc = dq.renderVals().deckCards.find((x) => x.center);
  if (!dc.prevNone) fail('a Word file should offer open-in-tab, not a preview'); dc.prevClose();
}
dq.deckGo(-1); dc = dq.renderVals().deckCards.find((x) => x.center);
if (!/Pitch to X$/.test(dc.title) || !dc.hasDemo || dc.link !== 'https://demo-x.workers.dev' || !/Hi X team/.test(dc.body)) fail('pitch card wrong', dc.title);
dc.demo(); dc = dq.renderVals().deckCards.find((x) => x.center); if (!dc.prevBox || dc.prevSandbox !== 'allow-scripts') fail('demo preview wrong');
dq.deckGo(2); dc = dq.renderVals().deckCards.find((x) => x.center);
if (!/Sell 352 units/.test(JSON.stringify(dc.rows)) || !/in 20 min/.test(JSON.stringify(dc.rows)) || dc.okLabel !== 'Approve trade') fail('trade card wrong', JSON.stringify(dc.rows));
dc.reject(); if (posts[posts.length - 1] !== '/api/approvals/3/rejected') fail('reject did not post', posts.join());
const nd = mk({ liveUp: true, live: live.empty, mode: 'decide' }).renderVals().deckCards;
if (nd.length !== 1 || nd[0].title !== 'Nothing waiting' || nd[0].hasActs) fail('empty decision deck wrong');
// master desk: stages as chips, one card per record, artifacts previewed in the card
globalThis.fetch = async (url) => ({ ok: url === '/api/desk/web', json: async () => ({ master: 'web', name: 'WEB DESIGNER',
  stages: [{ id: 'building', label: 'Building', count: 0 }, { id: 'live', label: 'Live', count: 1 }, { id: 'pitched', label: 'Pitched', count: 1 }],
  items: [{ id: 'l1', stage: 'live', title: 'Hot Nails', sub: 'Nail salon', ts: 1790000000, rows: [['Phone', '519 555 0101']], body: '', links: [{ label: 'Live demo', url: 'https://demo-hot-nails.x.workers.dev' }], files: [] },
    { id: 'l2', stage: 'pitched', title: '77 Bakery', sub: 'Bakery', ts: 1790000500, rows: [['Phone', '519 326 0000']], body: 'Hi 77 Bakery team', links: [{ label: 'Live demo', url: 'https://demo-77.x.workers.dev' }], files: [{ label: 'Local page', url: '/api/files/sites/77-bakery/index.html', mime: 'text/html' }] }] }) });
const dk = mk({ liveUp: true, live: live.full }); dk.speak = () => {};
await dk.openDesk('web'); let kv2 = dk.renderVals(); let kc = kv2.deckCards.find((x) => x.center);
if (dk.state.mode !== 'desk' || !kv2.deskOn || kv2.deskStages.map((x) => x.label).join() !== 'Building · 0,Live · 1,Pitched · 1') fail('desk stages wrong', JSON.stringify(kv2.deskStages.map((x) => x.label)));
if (!kc || kc.title !== 'Hot Nails' || !/holo-chip-on/.test(kv2.deskStages[1].cls)) fail('desk should open on the first stage that has records', kc && kc.title);
kv2.deskStages[2].pick(); kc = dk.renderVals().deckCards.find((x) => x.center);
if (kc.title !== '77 Bakery' || !/Hi 77 Bakery/.test(kc.body) || kc.atts.length !== 2 || !/519 326/.test(JSON.stringify(kc.rows))) fail('approved pitch card wrong', kc.title, kc.atts.length);
kc.atts[0].open(); kc = dk.renderVals().deckCards.find((x) => x.center);
if (!kc.showPrev || !kc.prevBox || kc.prevSrc !== '/api/files/sites/77-bakery/index.html' || kc.prevSandbox !== 'allow-scripts') fail('local demo page preview wrong');
await dk.openDesk('news'); kc = dk.renderVals().deckCards.find((x) => x.center); if (!/Could not load/.test(kc.title)) fail('a desk that fails to load should say so', kc.title);
dk.runCommand('show my approved pitches'); if (dk.state.deskFor !== 'web' || dk.state.deskStage !== 'pitched') fail('"approved pitches" should open the Web Designer desk on Pitched');
console.log('spoken:', said.map((x) => x.slice(0, 70)));
console.log(fails ? fails + ' problem(s)' : 'dashboard logic OK: no crashes, no sample values while connected, deck works');
process.exit(fails ? 1 : 0);
