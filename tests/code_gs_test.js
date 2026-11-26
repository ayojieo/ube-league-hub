// Dry run of apps-script/Code.gs with stand-ins for Google's services. Nothing here touches Google.
// Run:  node tests/code_gs_test.js [file to write the tab=league answer to]
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const code = fs.readFileSync(path.join(__dirname, '..', 'apps-script', 'Code.gs'), 'utf8');

let pass = 0; let fail = 0;
const check = (name, ok, detail) => { if (ok) pass += 1; else fail += 1; console.log((ok ? '  ok   ' : '  FAIL ') + name + (!ok && detail !== undefined ? ' -> ' + JSON.stringify(detail) : '')); };

function makeWorld(now) {
  const world = { sheets: [], triggers: [], mail: [], props: { PASSCODE: 'ube-pass' }, now };
  class Range {
    constructor(sh, r, c, nr, nc) { Object.assign(this, { sh, r, c, nr, nc }); }
    getSheet() { return this.sh; }
    cells(fn) { for (let i = 0; i < this.nr; i += 1) for (let j = 0; j < this.nc; j += 1) fn(this.r + i, this.c + j, i, j); }
    setValues(v) {
      if (v.length !== this.nr || v.some((row) => row.length !== this.nc)) throw new Error('setValues size mismatch on ' + this.sh.name);
      this.cells((r, c, i, j) => { this.sh.cell[r + ',' + c] = String(v[i][j]); }); return this;
    }
    clearContent() { this.cells((r, c) => { delete this.sh.cell[r + ',' + c]; }); return this; }
    getValues() { const out = []; for (let i = 0; i < this.nr; i += 1) { out.push([]); for (let j = 0; j < this.nc; j += 1) out[i].push(this.sh.cell[(this.r + i) + ',' + (this.c + j)] || ''); } return out; }
    getDisplayValues() { return this.getValues(); }
    getDisplayValue() { return this.getValues()[0][0]; }
    setNumberFormat(f) { this.sh.format.push([this.r, this.c, this.nr, this.nc, f]); return this; }
    setFontWeight(w) { this.cells((r, c) => { this.sh.bold[r + ',' + c] = w; }); return this; }
    setDataValidation(rule) { this.sh.rules.push({ r: this.r, c: this.c, nr: this.nr, nc: this.nc, rule }); return this; }
    protect() { const p = { range: this, desc: '', warning: false, setDescription(d) { p.desc = d; return p; }, getDescription() { return p.desc; }, setWarningOnly(w) { p.warning = w; return p; } }; this.sh.protections.push(p); return p; }
  }
  class Sheet {
    constructor(name) { Object.assign(this, { name, cell: {}, format: [], bold: {}, rules: [], protections: [], frozen: 0, widths: {} }); }
    getName() { return this.name; }
    getParent() { return ss; }
    getMaxRows() { return 1000; }
    getLastRow() { let last = 0; Object.keys(this.cell).forEach((k) => { if (this.cell[k] !== '') last = Math.max(last, Number(k.split(',')[0])); }); return last; }
    getLastColumn() { let last = 0; Object.keys(this.cell).forEach((k) => { if (this.cell[k] !== '') last = Math.max(last, Number(k.split(',')[1])); }); return last; }
    getRange(r, c, nr, nc) { if (r < 1 || c < 1 || (nr !== undefined && nr < 1)) throw new Error('bad range'); return new Range(this, r, c, nr === undefined ? 1 : nr, nc === undefined ? 1 : nc); }
    getDataRange() { return new Range(this, 1, 1, Math.max(this.getLastRow(), 1), Math.max(this.getLastColumn(), 1)); }
    setFrozenRows(n) { this.frozen = n; }
    setColumnWidth(c, w) { this.widths[c] = w; }
    getProtections() { return this.protections; }
  }
  const ss = {
    getSheetByName: (n) => world.sheets.find((s) => s.name === n) || null,
    insertSheet: (n) => { if (ss.getSheetByName(n)) throw new Error('sheet exists: ' + n); const s = new Sheet(n); world.sheets.push(s); return s; },
    getUrl: () => 'https://docs.google.com/spreadsheets/d/TEST/edit',
    getOwner: () => ({ getEmail: () => 'owner@example.com' }),
  };
  const builder = () => { const b = { kind: '', args: null, allowInvalid: null, requireValueInRange(r, d) { b.kind = 'range'; b.args = r; b.dropdown = d; return b; }, requireValueInList(l, d) { b.kind = 'list'; b.args = l; b.dropdown = d; return b; }, setAllowInvalid(v) { b.allowInvalid = v; return b; }, build() { return b; } }; return b; };
  const trigger = () => { const t = { fn: '', setup: {}, timeBased() { return t; }, onWeekDay(d) { t.setup.day = d; return t; }, atHour(h) { t.setup.hour = h; return t; }, inTimezone(z) { t.setup.tz = z; return t; }, create() { world.triggers.push(t); return t; }, getHandlerFunction() { return t.fn; } }; return t; };
  class FakeDate extends Date { constructor(...a) { if (a.length) super(...a); else super(world.now); } static now() { return new Date(world.now).getTime(); } }
  const sandbox = {
    Date: FakeDate,
    SpreadsheetApp: { getActiveSpreadsheet: () => ss, newDataValidation: builder, ProtectionType: { RANGE: 'RANGE' } },
    ContentService: { MimeType: { JSON: 'json' }, createTextOutput: (t) => ({ text: t, setMimeType() { return this; } }) },
    PropertiesService: { getScriptProperties: () => ({ getProperty: (k) => world.props[k] || null }) },
    LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
    ScriptApp: { WeekDay: { MONDAY: 'MONDAY', TUESDAY: 'TUESDAY' }, newTrigger: (fn) => { const t = trigger(); t.fn = fn; return t; }, getProjectTriggers: () => world.triggers.slice(), deleteTrigger: (t) => { world.triggers = world.triggers.filter((x) => x !== t); } },
    MailApp: { sendEmail: (to, subject, body) => world.mail.push({ to, subject, body }) },
    Session: { getEffectiveUser: () => ({ getEmail: () => 'me@example.com' }) },
    Utilities: { formatDate: (d, tz, fmt) => { const p = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d); return fmt === 'yyyy-MM-dd' ? p : new Intl.DateTimeFormat('en-US', { timeZone: tz, month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }).format(d); } },
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  world.gs = sandbox; world.ss = ss;
  world.dump = () => JSON.stringify(world.sheets.map((s) => [s.name, s.cell, s.rules.length, s.protections.length, s.frozen, s.format.length]));
  return world;
}

const body = (out) => JSON.parse(out.text);
const w = makeWorld('2026-11-16T07:40:00Z'); // Monday Nov 16 2026, 3:40 PM Manila
const g = w.gs;

console.log('1. setup on a sheet that only has the market tab');
g.setup();
const market0 = JSON.stringify(w.ss.getSheetByName('market').cell);
check('tabs created', ['market', 'Info', 'Scores', 'Standings', 'Rosters', 'Trades'].every((n) => w.ss.getSheetByName(n)), w.sheets.map((s) => s.name));
const tab = (n) => w.ss.getSheetByName(n);
const head = (n) => tab(n).getRange(1, 1, 1, tab(n).getLastColumn()).getValues()[0];
check('headers', head('Scores').join('|') === 'week|team_a|cats_a|cats_b|team_b|status' && head('Standings').join('|') === 'rank|team|w|l|t'
  && head('Rosters').join('|') === 'team|player|nba_team|pos|slot|status' && head('Trades').join('|') === 'team_a|a_gets|team_b|b_gets|processes');
check('seeded with the current data: 30 matchups (Weeks 1-6), 10 teams, all rosters, no pending trades', tab('Scores').getLastRow() === 31 && tab('Standings').getLastRow() === 12 && tab('Rosters').getLastRow() > 150 && tab('Trades').getLastRow() === 2,
  [tab('Scores').getLastRow(), tab('Standings').getLastRow(), tab('Rosters').getLastRow(), tab('Trades').getLastRow()]);
check('END row closes Standings, Rosters and Trades, not Scores', ['Standings', 'Rosters', 'Trades'].every((n) => tab(n).cell[tab(n).getLastRow() + ',1'] === 'END') && tab('Scores').cell[tab('Scores').getLastRow() + ',1'] === '6');
check('header bold and frozen, plain text', ['Scores', 'Standings', 'Rosters', 'Trades'].every((n) => tab(n).frozen === 1 && tab(n).bold['1,1'] === 'bold' && tab(n).format.some((f) => f[4] === '@' && f[0] === 1 && f[2] === 1000)));
check('header protection is warning-only', ['Scores', 'Standings', 'Rosters', 'Trades'].every((n) => tab(n).protections.length === 1 && tab(n).protections[0].warning === true && tab(n).protections[0].range.r === 1 && tab(n).protections[0].range.nr === 1));
const rules = (n) => tab(n).rules;
check('dropdowns warn, never reject', ['Scores', 'Standings', 'Rosters', 'Trades'].every((n) => rules(n).length > 0 && rules(n).every((x) => x.rule.allowInvalid === true && x.r === 2)));
check('team columns use the Info team list', rules('Scores').filter((x) => x.rule.kind === 'range').map((x) => x.c).join() === '2,5' && rules('Rosters').filter((x) => x.rule.kind === 'range').map((x) => x.c).join() === '1'
  && rules('Trades').filter((x) => x.rule.kind === 'range').map((x) => x.c).join() === '1,3' && rules('Scores')[0].rule.args.sh.name === 'Info' && rules('Scores')[0].rule.args.r === 11 && rules('Scores')[0].rule.args.nr === 10);
check('status and slot lists', rules('Scores').find((x) => x.c === 6).rule.args.join() === 'Final,In progress,Not started' && rules('Rosters').find((x) => x.c === 5).rule.args.join() === 'PG,SG,G,SF,PF,F,C,Util,BN,IL,IL+'
  && rules('Rosters').find((x) => x.c === 6).rule.args.join() === 'O,Q,GTD,DTD,INJ,SUSP');
const info = tab('Info');
check('Info: notes, team list, last pasted time', info.cell['11,2'] === 'The Haliban' && info.cell['14,2'] === 'Master Luka’s Cotton Pickers' && info.cell['20,1'] === '10' && info.cell['2,2'] === '2026-11-16T07:40:00.000Z' && /Nov 16, 2026/.test(info.cell['2,3']) && info.cell['5,1'] === 'Scores', [info.cell['2,2'], info.cell['2,3']]);

console.log('2. setup again changes nothing');
tab('Rosters').getRange(2, 5, 1, 1).setValues([['BN']]);
tab('Trades').getRange(2, 1, 2, 5).setValues([['END', '', '', '', ''], ['', '', '', '', '']]); // no pending trades any more
const before = w.dump();
g.setup(); g.setup();
check('no tab touched, no duplicate protection, market untouched', w.dump() === before && JSON.stringify(tab('market').cell) === market0);
tab('Trades').getRange(2, 1, 1, 5).setValues([['Nathan\'s Nifty Team', 'Karl-Anthony Towns', 'JJ\'s Official Team', 'Derrick White, Devin Booker', 'Pending vote']]);
tab('Trades').getRange(3, 1, 1, 1).setValues([['END']]);

console.log('3. web app');
const market = body(g.doGet());
check('default answer is the market, unchanged', market.ok === true && Array.isArray(market.rows) && market.rows.length === 10 && Object.keys(market).join() === 'ok,rows' && Object.keys(market.rows[0]).join() === 'id,team,trade_block,untouchables,targets,updatedAt', Object.keys(market));
check('other parameters still give the market', body(g.doGet({ parameter: { t: '123' } })).rows.length === 10 && body(g.doGet({})).rows.length === 10);
const league = body(g.doGet({ parameter: { tab: 'league' } }));
check('tab=league answer', league.ok === true && league.updated === '2026-11-16T07:40:00.000Z' && league.teams.length === 10 && league.teams[3].team_id === '4' && league.scores.length === 30 && league.standings.length === 11
  && league.rosters.length === tab('Rosters').getLastRow() - 1 && league.trades.length === 2 && Object.keys(league).join() === 'ok,updated,teams,scores,standings,rosters,trades', Object.keys(league));
check('rows are trimmed text keyed by header', JSON.stringify(league.scores[0]) === JSON.stringify({ week: '1', team_a: 'The Haliban', cats_a: '5', cats_b: '4', team_b: 'Nathaniel\'s Notable Team', status: 'Final' }), league.scores[0]);
tab('Scores').getRange(40, 1, 1, 6).setValues([[' 7 ', ' The Haliban', '5', '3', 'JJ\'s Official Team ', 'In progress']]);
const again = body(g.doGet({ parameter: { tab: 'league' } }));
check('blank rows skipped, spaces trimmed', again.scores.length === 31 && again.scores[30].week === '7' && again.scores[30].team_b === 'JJ\'s Official Team', again.scores.length);
tab('Scores').cell = Object.fromEntries(Object.entries(tab('Scores').cell).filter(([k]) => Number(k.split(',')[0]) !== 40));
const savedMarket = JSON.stringify(tab('market').cell);
check('doPost: wrong passcode refused', body(g.doPost({ postData: { contents: JSON.stringify({ passcode: 'nope', id: 'the-haliban', team: 'x' }) } })).error === 'wrong passcode' && JSON.stringify(tab('market').cell) === savedMarket);
const ok = body(g.doPost({ postData: { contents: JSON.stringify({ passcode: 'ube-pass', id: 'yaxel-and-em', team: 'Yaxel and Em', trade_block: 'A', untouchables: 'B', targets: 'C' }) } }));
check('doPost: saves with the passcode, same row', ok.ok === true && body(g.doGet()).rows.find((r) => r.id === 'yaxel-and-em').trade_block === 'A' && body(g.doGet()).rows.length === 10);
check('doPost: bad id refused', body(g.doPost({ postData: { contents: JSON.stringify({ passcode: 'ube-pass', id: 'Bad Id!' }) } })).error === 'bad id');
const stampBefore = info.cell['2,2'];
check('market save does not move the last-pasted time', stampBefore === '2026-11-16T07:40:00.000Z');

console.log('4. onEdit');
w.now = '2026-11-17T01:00:00Z';
g.onEdit({ range: tab('market').getRange(2, 1, 1, 1) });
check('edit on the market tab: time not moved', info.cell['2,2'] === stampBefore);
g.onEdit({ range: tab('Rosters').getRange(2, 1, 5, 6) });
check('edit on a league tab: time written to Info', info.cell['2,2'] === '2026-11-17T01:00:00.000Z' && /Nov 17, 2026, 9:00/.test(info.cell['2,3']), [info.cell['2,2'], info.cell['2,3']]);
let threw = false; try { g.onEdit(); g.onEdit({}); } catch (err) { threw = true; }
check('onEdit never throws', !threw);

console.log('5. reminder');
check('off by default', w.triggers.length === 0);
g.enableReminder(); g.enableReminder();
check('enableReminder: one Tuesday 10 AM Manila trigger, even when run twice', w.triggers.length === 1 && w.triggers[0].fn === 'weeklyReminder' && w.triggers[0].setup.day === 'TUESDAY' && w.triggers[0].setup.hour === 10 && w.triggers[0].setup.tz === 'Asia/Manila', w.triggers.map((t) => t.setup));
w.now = '2026-11-17T02:05:00Z'; // Tuesday 10:05 AM Manila: the week that just ended is Week 4
g.weeklyReminder();
check('Week 4 already Final: no email', w.mail.length === 0);
w.now = '2026-11-24T02:05:00Z'; // next Tuesday: Week 5 is Final in the seed
g.weeklyReminder();
check('Week 5 already Final: no email', w.mail.length === 0);
w.now = '2026-12-01T02:05:00Z'; // Week 6 has no Final rows
g.weeklyReminder();
check('no Final rows for the week that just ended: email with the sheet link', w.mail.length === 1 && w.mail[0].to === 'owner@example.com' && w.mail[0].subject === 'Paste the weekly UBE update' && w.mail[0].body.includes('Week 6') && w.mail[0].body.includes('https://docs.google.com/spreadsheets/d/TEST/edit'), w.mail);
w.now = '2027-03-16T02:05:00Z'; // after Week 19
g.weeklyReminder();
check('no email after the regular season', w.mail.length === 1);
g.disableReminder();
check('disableReminder removes it', w.triggers.length === 0);

console.log('6. league tabs missing (setup not run yet)');
const w2 = makeWorld('2026-11-16T07:40:00Z');
w2.gs.sheet_();
const miss = body(w2.gs.doGet({ parameter: { tab: 'league' } }));
check('clear error, market still works', miss.ok === false && /missing tabs: Scores/.test(miss.error) && body(w2.gs.doGet()).rows.length === 10, miss);

console.log('7. loadCurrentData replaces the league rows with the current data');
const w3 = makeWorld('2026-11-27T07:40:00Z');
w3.gs.setup();
const t3 = (n) => w3.ss.getSheetByName(n);
const seeded = JSON.stringify(['Scores', 'Standings', 'Rosters', 'Trades'].map((n) => t3(n).cell));
t3('Scores').getRange(2, 1, 1, 6).setValues([['1', 'Old Team', '0', '0', 'Other Team', 'Final']]);
t3('Rosters').getRange(400, 1, 1, 6).setValues([['Old Team', 'Old Player', 'LAL', 'C', 'BN', '']]);
t3('Trades').getRange(2, 1, 3, 5).setValues([['A', 'x', 'B', 'y', 'Pending vote'], ['END', '', '', '', ''], ['C', 'z', 'D', 'w', '']]);
const rules3 = ['Scores', 'Rosters'].map((n) => t3(n).rules.length + '/' + t3(n).protections.length).join();
const market3 = JSON.stringify(t3('market').cell);
w3.now = '2026-11-27T08:00:00Z';
w3.gs.loadCurrentData();
check('league rows back to the current data, old rows below gone', JSON.stringify(['Scores', 'Standings', 'Rosters', 'Trades'].map((n) => t3(n).cell)) === seeded);
check('headers, dropdowns, protection and market kept', ['Scores', 'Rosters'].map((n) => t3(n).rules.length + '/' + t3(n).protections.length).join() === rules3 && JSON.stringify(t3('market').cell) === market3 && t3('Scores').cell['1,1'] === 'week');
check('last-pasted time updated', t3('Info').cell['2,2'] === '2026-11-27T08:00:00.000Z');
const w4 = makeWorld('2026-11-27T07:40:00Z');
w4.gs.sheet_();
w4.gs.loadCurrentData();
check('works on a sheet without league tabs too', ['Info', 'Scores', 'Standings', 'Rosters', 'Trades'].every((n) => w4.ss.getSheetByName(n)) && w4.ss.getSheetByName('Scores').getLastRow() === 31);

if (process.argv[2]) fs.writeFileSync(process.argv[2], JSON.stringify(league));
console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
