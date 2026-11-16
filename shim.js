/* UBE League Hub: standalone runtime.
   Recreates what the page (page.html) expects from the Claude dashboard:
   window.dash (data, calc, onData, setLink, colors) and window.claude.use('db') for the Trade market.
   The page itself is loaded unchanged from page.html. */
(() => {
  'use strict';
  const DATASETS = ['standings', 'schedule', 'rosters', 'players', 'nba_games', 'managers', 'trades', 'injuries', 'news', 'log'];
  const PASS_KEY = 'ube-market-passcode';
  const bust = () => '?t=' + Math.floor(Date.now() / 60000);
  const getJSON = (url) => fetch(url + bust(), { cache: 'no-store' }).then((r) => { if (!r.ok) throw new Error(url + ' ' + r.status); return r.json(); });
  const el = (tag, attrs, text) => { const e = document.createElement(tag); Object.entries(attrs || {}).forEach(([k, v]) => e.setAttribute(k, v)); if (text != null) e.textContent = text; return e; };

  /* ---------- dash ---------- */
  const sources = {}; // id -> {status, data}
  const calcs = []; // {id, inputs, fn, key}
  const calcOut = {}; // id -> {status, data}
  const callbacks = [];
  let queued = false;
  let version = 0; const stamp = {};

  function data(id) {
    if (sources[id]) return sources[id];
    if (calcOut[id]) return calcOut[id];
    if (calcs.some((c) => c.id === id)) return { status: 'loading', data: null };
    return { status: 'missing', data: [] };
  }
  function runCalcs() {
    calcs.forEach((c) => {
      const ins = c.inputs.map((i) => data(i));
      if (ins.some((d) => d.status === 'error')) { calcOut[c.id] = { status: 'error', data: null }; return; }
      if (ins.some((d) => d.status !== 'ok')) return;
      const key = c.inputs.map((i) => stamp[i] || 0).join(',');
      if (c.key === key) return;
      c.key = key;
      try { calcOut[c.id] = { status: 'ok', data: c.fn(...ins.map((d) => d.data)) }; }
      catch (err) { console.error('calc ' + c.id, err); calcOut[c.id] = { status: 'error', data: null, message: String(err) }; }
      stamp[c.id] = ++version;
    });
  }
  function flush() {
    queued = false;
    runCalcs();
    callbacks.slice().forEach((fn) => { try { fn(); } catch (err) { console.error(err); } });
    afterDraw();
  }
  function queue() { if (!queued) { queued = true; Promise.resolve().then(flush); } }
  function setSource(id, status, rows) { sources[id] = { status, data: rows }; stamp[id] = ++version; queue(); }

  const colors = [];
  function readColors() {
    const cs = getComputedStyle(document.documentElement);
    colors.length = 0;
    for (let i = 1; i <= 8; i += 1) colors.push(cs.getPropertyValue('--cds-chart-categorical-' + i).trim() || '#2a78d6');
  }
  readColors();

  window.dash = {
    data,
    calc(id, def) { calcs.push({ id, inputs: def.inputs || [], fn: def.fn, key: null }); },
    onData(fn) { callbacks.push(fn); try { fn(); } catch (err) { console.error(err); } },
    setLink(name) { try { history.replaceState(null, '', '#' + name); } catch (err) { location.hash = name; } },
    colors,
    refresh() { loadData(); },
    params() { return {}; }, setParams() {}, resetParams() {},
  };

  let lastWidth = window.innerWidth; let resizeTimer = null;
  window.addEventListener('resize', () => {
    if (window.innerWidth === lastWidth) return;
    lastWidth = window.innerWidth; clearTimeout(resizeTimer); resizeTimer = setTimeout(queue, 150);
  });
  try { window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { readColors(); queue(); }); } catch (err) { /* older browsers */ }

  /* Things done after each draw, outside the page's own code. */
  function afterDraw() {
    const news = sources.news; const table = document.getElementById('news-table');
    if (table && news && news.status === 'ok') table.classList.toggle('hub-no-angle', news.data.length > 0 && news.data.every((r) => !r.angle));
  }

  /* ---------- Trade market store (Google Sheet web app) ---------- */
  let site = {};
  function askPasscode() {
    return new Promise((resolve, reject) => {
      const card = document.getElementById('market-card');
      const old = document.getElementById('hub-pass'); if (old) old.remove();
      const box = el('div', { id: 'hub-pass' });
      const label = el('label', { for: 'hub-pass-input' }, 'Passcode to save changes');
      const input = el('input', { id: 'hub-pass-input', type: 'password', autocomplete: 'off' });
      const ok = el('button', { type: 'button' }, 'Continue');
      const cancel = el('button', { type: 'button', class: 'plain' }, 'Cancel');
      const done = (v) => { box.remove(); if (v) resolve(v); else reject(new Error('cancelled')); };
      ok.addEventListener('click', () => done(input.value.trim()));
      cancel.addEventListener('click', () => done(''));
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') done(input.value.trim()); });
      box.append(label, input, ok, cancel);
      if (card) card.insertBefore(box, card.children[1] || null); else document.body.appendChild(box);
      input.focus();
    });
  }
  const savedPass = () => { try { return localStorage.getItem(PASS_KEY) || ''; } catch (err) { return ''; } };
  const keepPass = (v) => { try { if (v) localStorage.setItem(PASS_KEY, v); else localStorage.removeItem(PASS_KEY); } catch (err) { /* private mode */ } };

  function marketDb(url) {
    let rows = null; let last = ''; const listeners = [];
    const snap = () => ({ docs: (rows || []).map((r) => ({ id: r.id, exists: true, data: () => ({ team: r.team, trade_block: r.trade_block || '', untouchables: r.untouchables || '', targets: r.targets || '', updatedAt: r.updatedAt || '' }) })) });
    const emit = () => listeners.forEach((l) => { try { l.cb(snap()); } catch (err) { console.error(err); } });
    async function pull() {
      try {
        const res = await fetch(url + (url.includes('?') ? '&' : '?') + 't=' + Date.now(), { redirect: 'follow' });
        const body = await res.json();
        const next = Array.isArray(body) ? body : body.rows;
        if (!Array.isArray(next)) throw new Error('bad market response');
        const text = JSON.stringify(next);
        if (text !== last) { last = text; rows = next; emit(); }
      } catch (err) { if (rows === null) listeners.forEach((l) => { if (l.err) l.err(err); }); }
    }
    let timer = null;
    return {
      collection() {
        return { onSnapshot(cb, err) { listeners.push({ cb, err }); if (rows) cb(snap()); if (!timer) { pull(); timer = setInterval(pull, 60000); } return () => {}; } };
      },
      doc(path) {
        const id = String(path).split('/').pop();
        return {
          async set(body) {
            let pass = savedPass(); if (!pass) pass = await askPasscode();
            const res = await fetch(url, { method: 'POST', redirect: 'follow', headers: { 'Content-Type': 'text/plain;charset=utf-8' }, body: JSON.stringify({ passcode: pass, id, team: body.team, trade_block: body.trade_block, untouchables: body.untouchables, targets: body.targets }) });
            const out = await res.json();
            if (!out || !out.ok) { keepPass(''); throw new Error((out && out.error) || 'save failed'); }
            keepPass(pass);
            await pull();
          },
        };
      },
    };
  }
  window.claude = window.claude || {};
  window.claude.use = (name) => {
    if (name !== 'db') return Promise.reject(new Error('not available'));
    return ready.then(() => { if (!site.market_url || site.archived) throw new Error('no market store'); return marketDb(site.market_url); });
  };

  /* ---------- load ---------- */
  function loadData() {
    DATASETS.forEach((id) => {
      getJSON('data/' + id + '.json').then((rows) => setSource(id, 'ok', Array.isArray(rows) ? rows : []), () => setSource(id, 'error', []));
    });
  }
  function mountPage(html) {
    const root = document.getElementById('dash-root');
    const tpl = document.createElement('template'); tpl.innerHTML = html;
    const scripts = [...tpl.content.querySelectorAll('script')].map((s) => { const code = s.textContent; s.remove(); return code; });
    root.replaceChildren(tpl.content);
    // Each script runs in order, in its own scope, as on the Claude dashboard.
    scripts.forEach((code, i) => {
      try { (0, eval)('(function(){' + code + '\n})();\n//# sourceURL=page-script-' + (i + 1) + '.js'); }
      catch (err) { console.error('page script ' + (i + 1), err); }
    });
  }
  function footer(state, archive) {
    const foot = document.getElementById('hub-foot'); if (!foot) return;
    const parts = [];
    if (state && state.updated) {
      const d = new Date(state.updated);
      if (!isNaN(d)) parts.push(document.createTextNode('Updated ' + d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })));
    }
    if (!site.archived && Array.isArray(archive) && archive.length) {
      const span = el('span', null, 'Past seasons: ');
      archive.forEach((s, i) => { if (i) span.append(', '); span.append(el('a', { href: 'archive/' + encodeURIComponent(s) + '/' }, s)); });
      parts.push(span);
    }
    if (site.archived) parts.push(el('a', { href: '../../' }, 'Back to the current season'));
    foot.replaceChildren(...parts.flatMap((p, i) => (i ? [document.createTextNode(' · '), p] : [p])));
  }
  function banner(state, archive) {
    const b = document.getElementById('hub-banner'); if (!b) return;
    if (site.archived) { b.textContent = 'Archive: ' + (site.season || '') + ' season (final)'; b.hidden = false; return; }
    if (state && state.season_over) {
      b.replaceChildren(document.createTextNode('The ' + (state.season || '') + ' season is over. '));
      if (Array.isArray(archive) && archive.includes(state.season)) b.append(el('a', { href: 'archive/' + encodeURIComponent(state.season) + '/' }, 'View the final hub'));
      b.hidden = false;
    }
  }

  const optional = (url, fallback) => getJSON(url).catch(() => fallback);
  const ready = optional('config/site.json', {}).then((s) => { site = s || {}; });
  const extras = ready.then(() => Promise.all([optional('data/state.json', {}), site.archived ? [] : optional('archive/index.json', [])]));
  extras.then(([state, archive]) => {
    banner(state, archive); footer(state, archive);
    // After a season is archived the live data is empty: show only the banner until the next season starts.
    if (state && state.season_over && !site.archived) return null;
    return fetch('page.html' + bust(), { cache: 'no-store' }).then((r) => { if (!r.ok) throw new Error('page.html ' + r.status); return r.text(); }).then((html) => { mountPage(html); loadData(); });
  }).catch((err) => {
    console.error(err);
    document.getElementById('dash-root').textContent = 'The hub could not load. Please refresh.';
  });
})();
