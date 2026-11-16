/**
 * UBE League Hub: Trade market store.
 * Lives in the Google Sheet "UBE Trade Market" (Extensions > Apps Script).
 * - Anyone can read the entries (the hub page shows them).
 * - Saving needs the passcode. Set it in Project Settings > Script Properties: name PASSCODE.
 *   The passcode is never written in this file.
 */
var SHEET = 'market';
var HEAD = ['id', 'team', 'trade_block', 'untouchables', 'targets', 'updatedAt'];
var MAX = 2000;
var SEED = [
  [
    "the-haliban",
    "The Haliban",
    "Ryan Rollins\nAnthony Black\nToumani Camara\nTrey Murphy",
    "Tyrese Haliburton\nJalen Johnson\nDyson Daniels\nBam Adebayo",
    "Walker Kessler\nJarret Allen\nDaniel Gafford\nDavion Mitchell",
    "2026-11-14T14:16:28.123Z"
  ],
  [
    "yaxel-and-em",
    "Yaxel and Em",
    "",
    "",
    "",
    ""
  ],
  [
    "paulo-s-perfect-team",
    "Paulo's Perfect Team",
    "Immanuel Quickley\nKeyonte George\nDarryn Peterson\nNic Claxton",
    "",
    "",
    "2026-11-14T14:15:38.277Z"
  ],
  [
    "master-luka-s-cotton-pickers",
    "Master Luka’s Cotton Pickers",
    "",
    "",
    "",
    "2026-11-10T06:56:03.740Z"
  ],
  [
    "davraa-boys",
    "DAVRAA Boys",
    "",
    "",
    "",
    "2026-11-10T06:56:00.537Z"
  ],
  [
    "nathaniel-s-notable-team",
    "Nathaniel's Notable Team",
    "",
    "",
    "",
    ""
  ],
  [
    "jayden-s-amazing-team",
    "Jayden's Amazing Team",
    "",
    "",
    "",
    "2026-11-10T06:55:57.510Z"
  ],
  [
    "nathan-s-nifty-team",
    "Nathan's Nifty Team",
    "Josh Hart",
    "",
    "",
    "2026-11-14T14:16:18.859Z"
  ],
  [
    "jj-s-official-team",
    "JJ's Official Team",
    "",
    "",
    "",
    ""
  ],
  [
    "barangay-ginebra-san-miguel",
    "Barangay Ginebra San Miguel",
    "",
    "",
    "",
    "2026-11-10T06:56:06.349Z"
  ]
];

function sheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET);
  if (!sh) {
    sh = ss.insertSheet(SHEET);
    sh.getRange(1, 1, 1, HEAD.length).setValues([HEAD]).setFontWeight('bold');
    sh.getRange(2, 1, SEED.length, HEAD.length).setNumberFormat('@').setValues(SEED);
    sh.setFrozenRows(1);
  }
  return sh;
}

/** Run this once by hand (Run > setup) to create the "market" tab with the current entries. */
function setup() {
  sheet_();
}

function rows_() {
  var values = sheet_().getDataRange().getDisplayValues();
  var out = [];
  for (var i = 1; i < values.length; i++) {
    if (!values[i][0]) continue;
    var row = {};
    for (var c = 0; c < HEAD.length; c++) row[HEAD[c]] = String(values[i][c] || '');
    out.push(row);
  }
  return out;
}

function json_(value) {
  return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
}

function doGet() {
  return json_({ ok: true, rows: rows_() });
}

function doPost(e) {
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    var pass = PropertiesService.getScriptProperties().getProperty('PASSCODE');
    if (!pass) return json_({ ok: false, error: 'passcode not set' });
    if (String(body.passcode || '') !== pass) return json_({ ok: false, error: 'wrong passcode' });
    var id = String(body.id || '').toLowerCase();
    if (!/^[a-z0-9-]{1,80}$/.test(id)) return json_({ ok: false, error: 'bad id' });
    var clean = function (v) { return String(v == null ? '' : v).slice(0, MAX); };
    var row = [id, clean(body.team).slice(0, 80), clean(body.trade_block), clean(body.untouchables), clean(body.targets), new Date().toISOString()];
    var lock = LockService.getScriptLock();
    lock.waitLock(10000);
    try {
      var sh = sheet_();
      var ids = sh.getRange(1, 1, Math.max(sh.getLastRow(), 1), 1).getDisplayValues();
      var at = -1;
      for (var i = 1; i < ids.length; i++) if (ids[i][0] === id) { at = i + 1; break; }
      if (at < 0) at = sh.getLastRow() + 1;
      sh.getRange(at, 1, 1, HEAD.length).setNumberFormat('@').setValues([row]);
    } finally {
      lock.releaseLock();
    }
    return json_({ ok: true });
  } catch (err) {
    return json_({ ok: false, error: 'could not save' });
  }
}
