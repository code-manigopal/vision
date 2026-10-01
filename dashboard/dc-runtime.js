/* VISION dashboard runtime
 * Renders Main.dc.html (the design from the canvas) locally, so the same file works in both places.
 * Supports what the dashboard uses: {{holes}} in text and attributes, <sc-for>, <sc-if>, <helmet>,
 * and a logic class with state / setState / renderVals / componentDidMount / componentWillUnmount.
 * Renders with Preact (vendored, no network needed).
 */
(function () {
  'use strict';
  const { h, render, Fragment } = window.preact;

  // ---------- 1. tiny case-preserving HTML parser (keeps viewBox, onClick, etc.) ----------
  const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr']);
  const ENT = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: '\u00a0', '#39': "'" };
  const decode = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|\w+);/gi, (m, e) => {
    if (e[0] === '#') return String.fromCodePoint(e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
    return ENT[e] !== undefined ? ENT[e] : m;
  });

  function parse(src) {
    const root = { tag: '#root', attrs: {}, children: [] };
    const stack = [root];
    let i = 0;
    const top = () => stack[stack.length - 1];
    while (i < src.length) {
      if (src.startsWith('<!--', i)) { const e = src.indexOf('-->', i); i = e < 0 ? src.length : e + 3; continue; }
      if (src[i] === '<' && src[i + 1] === '/') {
        const e = src.indexOf('>', i); const name = src.slice(i + 2, e).trim();
        for (let k = stack.length - 1; k > 0; k--) if (stack[k].tag === name) { stack.length = k; break; }
        i = e + 1; continue;
      }
      if (src[i] === '<' && /[a-zA-Z]/.test(src[i + 1] || '')) {
        let j = i + 1; while (j < src.length && /[^\s/>]/.test(src[j])) j++;
        const tag = src.slice(i + 1, j); const attrs = {};
        let selfClose = false;
        while (j < src.length) {
          while (/\s/.test(src[j])) j++;
          if (src[j] === '>') { j++; break; }
          if (src[j] === '/' && src[j + 1] === '>') { selfClose = true; j += 2; break; }
          let k = j; while (k < src.length && /[^\s=/>]/.test(src[k])) k++;
          const name = src.slice(j, k); let val = '';
          j = k; while (/\s/.test(src[j])) j++;
          if (src[j] === '=') {
            j++; while (/\s/.test(src[j])) j++;
            const q = src[j];
            if (q === '"' || q === "'") { const e = src.indexOf(q, j + 1); val = src.slice(j + 1, e); j = e + 1; }
            else { let e = j; while (e < src.length && /[^\s>]/.test(src[e])) e++; val = src.slice(j, e); j = e; }
          }
          if (name) attrs[name] = decode(val);
        }
        const node = { tag, attrs, children: [] };
        top().children.push(node);
        if (tag === 'style' || tag === 'script') {
          const e = src.indexOf('</' + tag, j); node.children.push({ text: src.slice(j, e) }); i = src.indexOf('>', e) + 1; continue;
        }
        if (!selfClose && !VOID.has(tag.toLowerCase())) stack.push(node);
        i = j; continue;
      }
      const e = src.indexOf('<', i + 1); const end = e < 0 ? src.length : e;
      const text = src.slice(i, end);
      if (!(/^\s*$/.test(text) && text.includes('\n'))) top().children.push({ text: decode(text) });
      i = end;
    }
    return root;
  }

  // ---------- 2. holes ----------
  const HOLE = /\{\{\s*([^}]+?)\s*\}\}/g;
  function lookup(expr, scope) {
    expr = expr.trim();
    if (expr === 'true') return true; if (expr === 'false') return false;
    const parts = expr.split('.'); let v = scope[parts[0]];
    for (let k = 1; k < parts.length && v != null; k++) v = v[parts[k]];
    return v;
  }
  function interp(str, scope) {
    const whole = str.match(/^\{\{\s*([^}]+?)\s*\}\}$/);
    if (whole) return lookup(whole[1], scope);
    if (!str.includes('{{')) return str;
    return str.replace(HOLE, (_, e) => { const v = lookup(e, scope); return v == null ? '' : String(v); });
  }

  // ---------- 3. template -> Preact vnodes ----------
  function toVNodes(node, scope, key) {
    if (node.text !== undefined) {
      const v = interp(node.text, scope);
      return v == null || v === false ? null : String(v);
    }
    const kids = (sc) => node.children.map((c, i) => toVNodes(c, sc, i));
    if (node.tag === 'sc-for') {
      const list = lookup(node.attrs.list.replace(/[{}]/g, ''), scope) || [];
      const as = node.attrs.as || 'item';
      return h(Fragment, { key }, list.map((item, i) => h(Fragment, { key: i }, kids({ ...scope, [as]: item }))));
    }
    if (node.tag === 'sc-if') return lookup(node.attrs.value.replace(/[{}]/g, ''), scope) ? h(Fragment, { key }, kids(scope)) : null;
    if (node.tag === 'helmet') return null;
    const props = { key };
    for (const [name, raw] of Object.entries(node.attrs)) {
      if (name.startsWith('hint-') || name.startsWith('data-dc')) continue;
      let v = interp(raw, scope);
      if (v === undefined || v === null || v === false) continue;
      let n = name;
      if (n === 'onChange' && node.tag === 'input') n = 'onInput'; // live typing, like React
      props[n] = v;
    }
    return h(node.tag, props, kids(scope));
  }

  // ---------- 4. logic base class ----------
  let scheduleRender = () => {};
  class DCLogic {
    constructor(props) { this.props = props || {}; this.state = {}; }
    setState(patch, cb) {
      const p = typeof patch === 'function' ? patch(this.state, this.props) : patch;
      this.state = Object.assign({}, this.state, p);
      scheduleRender();
      if (cb) cb();
    }
  }
  window.DCLogic = DCLogic;

  // ---------- 5. boot ----------
  async function start() {
    const src = await (await fetch('/dashboard/Main.dc.html', { cache: 'no-store' })).text();
    const helmet = src.match(/<helmet>([\s\S]*?)<\/helmet>/);
    if (helmet) document.head.insertAdjacentHTML('beforeend', helmet[1]);
    const tpl = src.slice(src.indexOf('<x-dc>') + 6, src.indexOf('</x-dc>')).replace(/<helmet>[\s\S]*?<\/helmet>/, '');
    const code = src.match(/<script type="text\/x-dc"[^>]*>([\s\S]*?)<\/script>/)[1];
    const tree = parse(tpl);
    const Component = new Function('DCLogic', code + '\n;return Component;')(DCLogic);
    const logic = new Component({});
    const mount = document.getElementById('stage');
    let queued = false;
    const paint = () => {
      queued = false;
      const vals = Object.assign({}, logic.renderVals());
      render(h(Fragment, null, tree.children.map((c, i) => toVNodes(c, vals, i))), mount);
    };
    scheduleRender = () => { if (!queued) { queued = true; requestAnimationFrame(paint); } };
    paint();
    if (logic.componentDidMount) logic.componentDidMount();
    window.addEventListener('beforeunload', () => logic.componentWillUnmount && logic.componentWillUnmount());
    window.VISION = logic; // handy in the browser console
  }

  // ---------- 6. fill the browser window ----------
  // The design is authored at 1440x900; here we scale it up to the window and let the
  // artboard grow past 1440x900 so the layout uses all the space instead of letterboxing.
  function fit() {
    const s = Math.max(1, Math.min(window.innerWidth / 1440, window.innerHeight / 900));
    const el = document.getElementById('stage');
    el.style.width = Math.round(window.innerWidth / s) + 'px';
    el.style.height = Math.round(window.innerHeight / s) + 'px';
    el.style.transform = 'scale(' + s + ')';
    el.style.left = '0px';
    el.style.top = '0px';
  }
  window.addEventListener('resize', fit);
  document.addEventListener('DOMContentLoaded', () => { fit(); start().catch((e) => {
    document.getElementById('stage').innerHTML = '<pre style="color:#FF8A73;padding:24px">Dashboard failed to load:\n' + (e && e.stack || e) + '</pre>';
  }); });
})();
