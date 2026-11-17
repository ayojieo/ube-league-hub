/**
 * UBE League Hub: Google Sheet script (Extensions > Apps Script).
 *
 * 1. Trade market (tab "market")
 *    - Anyone can read the entries (the hub page shows them).
 *    - Saving needs the passcode. Set it in Project Settings > Script Properties: name PASSCODE.
 *      The passcode is never written in this file.
 * 2. League data (tabs Scores, Standings, Rosters, Trades, Info)
 *    - Used by the hub when config/sources.json says "league_data": "sheet".
 *    - Anyone can read them (same data the public hub shows). Only people who can edit the sheet can change them.
 *
 * After changing this file: Save, Run > setup, then Deploy > Manage deployments > pencil > Version: New version > Deploy.
 * The web app link stays the same.
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

/** Run this by hand (Run > setup). Safe to run again: it only creates tabs that are missing
 *  and never changes a tab that already has data rows. */
function setup() {
  sheet_();
  setupLeague_();
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

function doGet(e) {
  if (e && e.parameter && e.parameter.tab === 'league') return json_(league_());
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

/* ====================================================================================================
 * League data tabs: Scores, Standings, Rosters, Trades, Info.
 * The hub's daily update reads them when config/sources.json says "league_data": "sheet".
 * Team names are the Yahoo names (listed on the Info tab). The update turns them into the hub's names.
 * ==================================================================================================== */
var TZ = 'Asia/Manila';
var WEEK2_START = '2026-10-26'; // the Monday Week 2 starts (same as week2_start in config/league.json)
var LAST_WEEK = 19;             // last regular-season week
var REMINDER_HOUR = 10;         // reminder: Tuesday 10 AM Manila. Yahoo closes a week on Monday evening Manila time, so Tuesday is the first safe morning
var INFO = 'Info';
var INFO_STAMP_ROW = 2;         // Info!B2 holds the time a league tab was last changed
var INFO_TEAM_ROW = 11;         // Info!A11:B20 holds team number and Yahoo team name
var HEADER_NOTE = 'UBE header row';
var TABS = {
  Scores: { head: ['week', 'team_a', 'cats_a', 'cats_b', 'team_b', 'status'], teams: [2, 5], lists: { 6: ['Final', 'In progress'] }, end: false,
            note: 'One row per matchup: week, team, its categories won, the other team\'s categories won, other team, Final or In progress. Paste new weeks below the old rows.' },
  Standings: { head: ['rank', 'team', 'w', 'l', 't'], teams: [2], lists: {}, end: true,
               note: 'All 10 teams with total category wins, losses and ties. Click A1 and paste over the old table.' },
  Rosters: { head: ['team', 'player', 'nba_team', 'pos', 'slot', 'status'], teams: [1], end: true,
             lists: { 5: ['PG', 'SG', 'G', 'SF', 'PF', 'F', 'C', 'Util', 'BN', 'IL', 'IL+'], 6: ['O', 'Q', 'GTD', 'DTD', 'INJ', 'SUSP'] },
             note: 'Every rostered player. slot = the Yahoo lineup slot (IL and IL+ mean injured list). status = blank, O, Q, GTD, DTD, INJ or SUSP. Click A1 and paste over the old list.' },
  Trades: { head: ['team_a', 'a_gets', 'team_b', 'b_gets', 'processes'], teams: [1, 3], lists: {}, end: true,
            note: 'Pending trades only. a_gets and b_gets are player names with commas between them. No pending trades: leave only the header and an END row.' }
};
var LEAGUE_TABS = ['Scores', 'Standings', 'Rosters', 'Trades'];
var TEAMS = ["The Haliban", "Yaxel and Em", "Paulo's Perfect Team", "Master Luka’s Cotton Pickers", "DAVRAA Boys", "Nathaniel's Notable Team", "Jayden's Amazing Team", "Nathan's Nifty Team", "JJ's Official Team", "Barangay Ginebra San Miguel"];
var SEED_LEAGUE = {
  Scores: [
    ["1", "The Haliban", "5", "4", "Nathaniel's Notable Team", "Final"],
    ["1", "Yaxel and Em", "2", "7", "Jayden's Amazing Team", "Final"],
    ["1", "Paulo's Perfect Team", "6", "3", "JJ's Official Team", "Final"],
    ["1", "Master Luka’s Cotton Pickers", "2", "6", "DAVRAA Boys", "Final"],
    ["1", "Nathan's Nifty Team", "1", "8", "Barangay Ginebra San Miguel", "Final"],
    ["2", "The Haliban", "4", "5", "Paulo's Perfect Team", "Final"],
    ["2", "Yaxel and Em", "4", "5", "DAVRAA Boys", "Final"],
    ["2", "Master Luka’s Cotton Pickers", "6", "3", "Nathan's Nifty Team", "Final"],
    ["2", "Nathaniel's Notable Team", "5", "4", "Barangay Ginebra San Miguel", "Final"],
    ["2", "Jayden's Amazing Team", "5", "4", "JJ's Official Team", "Final"],
    ["3", "The Haliban", "4", "5", "Jayden's Amazing Team", "Final"],
    ["3", "Yaxel and Em", "7", "1", "JJ's Official Team", "Final"],
    ["3", "Paulo's Perfect Team", "4", "5", "Barangay Ginebra San Miguel", "Final"],
    ["3", "Master Luka’s Cotton Pickers", "5", "4", "Nathaniel's Notable Team", "Final"],
    ["3", "DAVRAA Boys", "8", "1", "Nathan's Nifty Team", "Final"],
    ["4", "The Haliban", "4", "5", "Yaxel and Em", "Final"],
    ["4", "Paulo's Perfect Team", "4", "5", "Master Luka’s Cotton Pickers", "Final"],
    ["4", "DAVRAA Boys", "5", "4", "JJ's Official Team", "Final"],
    ["4", "Nathaniel's Notable Team", "6", "3", "Nathan's Nifty Team", "Final"],
    ["4", "Jayden's Amazing Team", "6", "3", "Barangay Ginebra San Miguel", "Final"]
  ],
  Standings: [
    ["1", "DAVRAA Boys", "24", "11", "1"],
    ["2", "Jayden's Amazing Team", "23", "13", "0"],
    ["3", "Barangay Ginebra San Miguel", "20", "16", "0"],
    ["4", "Paulo's Perfect Team", "19", "17", "0"],
    ["5", "Nathaniel's Notable Team", "19", "17", "0"],
    ["6", "Yaxel and Em", "18", "17", "1"],
    ["7", "Master Luka’s Cotton Pickers", "18", "17", "1"],
    ["8", "The Haliban", "17", "19", "0"],
    ["9", "JJ's Official Team", "12", "23", "1"],
    ["10", "Nathan's Nifty Team", "8", "28", "0"]
  ],
  Rosters: [
    ["The Haliban", "Ryan Rollins", "MIL", "PG,SG", "PG", "O"],
    ["The Haliban", "Amen Thompson", "HOU", "PG,SG", "SG", ""],
    ["The Haliban", "Jamal Shead", "TOR", "PG", "G", ""],
    ["The Haliban", "Dyson Daniels", "ATL", "SG,SF", "SF", ""],
    ["The Haliban", "Collin Murray-Boyles", "TOR", "PF,C", "PF", ""],
    ["The Haliban", "Jalen Johnson", "ATL", "SF,PF", "F", ""],
    ["The Haliban", "Onyeka Okongwu", "ATL", "C", "C", ""],
    ["The Haliban", "Aday Mara", "OKC", "C", "C", ""],
    ["The Haliban", "Zaccharie Risacher", "DAL", "SF,PF", "Util", ""],
    ["The Haliban", "AJ Dybantsa", "WAS", "SF", "Util", ""],
    ["The Haliban", "Anthony Black", "ORL", "PG,SG,SF", "BN", ""],
    ["The Haliban", "Bam Adebayo", "MIA", "PF,C", "BN", ""],
    ["The Haliban", "Toumani Camara", "POR", "SF,PF", "BN", ""],
    ["The Haliban", "Trey Murphy III", "NOP", "SG,SF", "IL", "O"],
    ["The Haliban", "Tyrese Haliburton", "IND", "PG,SG", "IL", "O"],
    ["The Haliban", "Jalen Duren", "DET", "C", "IL", "O"],
    ["The Haliban", "Mark Williams", "PHX", "C", "IL", "O"],
    ["Yaxel and Em", "Jalen Brunson", "NYK", "PG", "PG", ""],
    ["Yaxel and Em", "Coby White", "CHA", "PG,SG", "SG", ""],
    ["Yaxel and Em", "Tyrese Maxey", "PHI", "PG", "G", ""],
    ["Yaxel and Em", "Matas Buzelis", "CHI", "SF,PF", "SF", ""],
    ["Yaxel and Em", "Keegan Murray", "SAC", "SF,PF", "PF", ""],
    ["Yaxel and Em", "Yaxel Lendeborg", "GSW", "SF,PF", "F", ""],
    ["Yaxel and Em", "Naz Reid", "CHA", "PF,C", "C", ""],
    ["Yaxel and Em", "Alperen Şengün", "HOU", "PF,C", "C", ""],
    ["Yaxel and Em", "Neemias Queta", "BOS", "C", "Util", ""],
    ["Yaxel and Em", "CJ McCollum", "ATL", "PG,SG", "Util", ""],
    ["Yaxel and Em", "Cedric Coward", "MEM", "SG,SF", "BN", ""],
    ["Yaxel and Em", "Duncan Robinson", "DET", "SG,SF", "BN", "Q"],
    ["Yaxel and Em", "Donovan Clingan", "POR", "C", "BN", ""],
    ["Yaxel and Em", "Peyton Watson", "CLE", "SF,PF", "IL", "Q"],
    ["Yaxel and Em", "Evan Mobley", "CLE", "PF,C", "IL", "O"],
    ["Paulo's Perfect Team", "Immanuel Quickley", "TOR", "PG,SG", "PG", ""],
    ["Paulo's Perfect Team", "Keyonte George", "UTA", "PG,SG", "SG", ""],
    ["Paulo's Perfect Team", "Jamal Murray", "DEN", "PG", "G", ""],
    ["Paulo's Perfect Team", "Derrick Jones Jr.", "LAC", "SF,PF", "SF", ""],
    ["Paulo's Perfect Team", "Cameron Boozer", "MEM", "PF", "PF", ""],
    ["Paulo's Perfect Team", "Ace Bailey", "UTA", "SF,PF", "F", ""],
    ["Paulo's Perfect Team", "Nikola Jokić", "DEN", "C", "C", ""],
    ["Paulo's Perfect Team", "Jabari Smith Jr.", "HOU", "PF,C", "C", ""],
    ["Paulo's Perfect Team", "Darryn Peterson", "UTA", "SG", "Util", ""],
    ["Paulo's Perfect Team", "Jarrett Allen", "CLE", "C", "Util", ""],
    ["Paulo's Perfect Team", "Egor Dëmin", "BKN", "PG,SG", "BN", ""],
    ["Paulo's Perfect Team", "Jaden McDaniels", "MIN", "SF", "BN", ""],
    ["Paulo's Perfect Team", "Nic Claxton", "CHI", "C", "BN", ""],
    ["Paulo's Perfect Team", "Kawhi Leonard", "TOR", "SG,SF,PF", "IL", "O"],
    ["Master Luka’s Cotton Pickers", "Trae Young", "WAS", "PG", "PG", ""],
    ["Master Luka’s Cotton Pickers", "Luka Dončić", "LAL", "PG,SG", "SG", ""],
    ["Master Luka’s Cotton Pickers", "Darius Acuff Jr.", "SAC", "PG", "G", ""],
    ["Master Luka’s Cotton Pickers", "Jayson Tatum", "BOS", "SF,PF", "SF", ""],
    ["Master Luka’s Cotton Pickers", "Tari Eason", "HOU", "SG,SF,PF", "PF", ""],
    ["Master Luka’s Cotton Pickers", "John Collins", "DET", "PF,C", "F", ""],
    ["Master Luka’s Cotton Pickers", "Alex Sarr", "WAS", "C", "C", ""],
    ["Master Luka’s Cotton Pickers", "Rudy Gobert", "MIN", "C", "C", ""],
    ["Master Luka’s Cotton Pickers", "Rui Hachimura", "LAC", "SF,PF", "Util", ""],
    ["Master Luka’s Cotton Pickers", "Davion Mitchell", "MIA", "PG", "Util", ""],
    ["Master Luka’s Cotton Pickers", "Donovan Mitchell", "CLE", "PG,SG", "BN", ""],
    ["Master Luka’s Cotton Pickers", "Jalen Smith", "CHI", "PF,C", "BN", "Q"],
    ["Master Luka’s Cotton Pickers", "Zach Edey", "MEM", "C", "BN", "Q"],
    ["Master Luka’s Cotton Pickers", "Caleb Wilson", "CHI", "PF", "IL", "O"],
    ["Master Luka’s Cotton Pickers", "Lauri Markkanen", "UTA", "SF,PF", "IL", "O"],
    ["Master Luka’s Cotton Pickers", "Paolo Banchero", "ORL", "PF", "IL", "O"],
    ["DAVRAA Boys", "Jrue Holiday", "POR", "PG,SG", "PG", ""],
    ["DAVRAA Boys", "Cooper Flagg", "DAL", "SG,SF,PF", "SG", ""],
    ["DAVRAA Boys", "Payton Pritchard", "BOS", "PG", "G", ""],
    ["DAVRAA Boys", "Kevin Durant", "HOU", "SG,SF,PF", "SF", ""],
    ["DAVRAA Boys", "Zion Williamson", "NOP", "PF,C", "PF", ""],
    ["DAVRAA Boys", "Miles Bridges", "PHX", "PF", "F", ""],
    ["DAVRAA Boys", "P.J. Washington", "DAL", "PF,C", "C", ""],
    ["DAVRAA Boys", "Walker Kessler", "LAL", "C", "C", ""],
    ["DAVRAA Boys", "Derik Queen", "NOP", "PF,C", "Util", ""],
    ["DAVRAA Boys", "Jonathan Kuminga", "MIN", "SF,PF", "Util", ""],
    ["DAVRAA Boys", "Paul Reed", "DET", "PF,C", "BN", ""],
    ["DAVRAA Boys", "Austin Reaves", "LAL", "PG,SG,SF", "IL", "O"],
    ["DAVRAA Boys", "Joel Embiid", "PHI", "C", "IL", "O"],
    ["DAVRAA Boys", "Stephen Curry", "GSW", "PG", "IL", "O"],
    ["DAVRAA Boys", "Ja Morant", "POR", "PG", "IL", "O"],
    ["DAVRAA Boys", "Jaren Jackson Jr.", "UTA", "PF,C", "IL", "O"],
    ["Nathaniel's Notable Team", "Ajay Mitchell", "OKC", "PG,SG", "PG", ""],
    ["Nathaniel's Notable Team", "James Harden", "CLE", "PG,SG", "SG", ""],
    ["Nathaniel's Notable Team", "Jaylen Brown", "PHI", "SG,SF,PF", "G", ""],
    ["Nathaniel's Notable Team", "Deni Avdija", "POR", "SG,SF,PF", "SF", ""],
    ["Nathaniel's Notable Team", "Pascal Siakam", "IND", "PF,C", "PF", ""],
    ["Nathaniel's Notable Team", "Jaylen Wells", "MEM", "SG,SF", "F", ""],
    ["Nathaniel's Notable Team", "Victor Wembanyama", "SAS", "C", "C", ""],
    ["Nathaniel's Notable Team", "Aaron Gordon", "DEN", "PF,C", "C", ""],
    ["Nathaniel's Notable Team", "De'Aaron Fox", "SAS", "PG", "Util", "O"],
    ["Nathaniel's Notable Team", "Brandon Miller", "CHA", "SF,PF", "Util", ""],
    ["Nathaniel's Notable Team", "Damian Lillard", "POR", "PG", "BN", ""],
    ["Nathaniel's Notable Team", "Julius Randle", "BKN", "PF", "BN", ""],
    ["Nathaniel's Notable Team", "LaMelo Ball", "MIN", "PG", "BN", ""],
    ["Nathaniel's Notable Team", "Zach LaVine", "SAC", "PG,SG,SF", "IL", "O"],
    ["Jayden's Amazing Team", "Shai Gilgeous-Alexander", "OKC", "PG", "PG", ""],
    ["Jayden's Amazing Team", "Naji Marshall", "DAL", "SG,SF,PF", "SG", ""],
    ["Jayden's Amazing Team", "Kris Dunn", "LAC", "PG,SG", "G", ""],
    ["Jayden's Amazing Team", "Julian Champagnie", "SAS", "SF,PF", "SF", ""],
    ["Jayden's Amazing Team", "Scottie Barnes", "TOR", "SF,PF,C", "PF", ""],
    ["Jayden's Amazing Team", "Anthony Davis", "WAS", "PF,C", "F", ""],
    ["Jayden's Amazing Team", "Moussa Diabaté", "CHA", "C", "C", ""],
    ["Jayden's Amazing Team", "Wendell Carter Jr.", "ORL", "C", "C", ""],
    ["Jayden's Amazing Team", "Nickeil Alexander-Walker", "ATL", "PG,SG", "Util", ""],
    ["Jayden's Amazing Team", "Tyler Herro", "MIL", "PG,SG", "Util", ""],
    ["Jayden's Amazing Team", "Brandin Podziemski", "GSW", "PG,SG", "BN", ""],
    ["Jayden's Amazing Team", "Yves Missi", "NOP", "C", "BN", ""],
    ["Jayden's Amazing Team", "Michael Porter Jr.", "BKN", "SF,PF", "BN", ""],
    ["Jayden's Amazing Team", "Fred VanVleet", "HOU", "PG", "IL", "O"],
    ["Jayden's Amazing Team", "Dejounte Murray", "NOP", "PG,SG", "IL", "O"],
    ["Jayden's Amazing Team", "Jimmy Butler III", "GSW", "SF,PF", "IL", "O"],
    ["Jayden's Amazing Team", "Chet Holmgren", "OKC", "PF,C", "IL", "O"],
    ["Nathan's Nifty Team", "Devin Booker", "PHX", "PG,SG", "PG", ""],
    ["Nathan's Nifty Team", "Dylan Harper", "SAS", "PG,SG", "SG", ""],
    ["Nathan's Nifty Team", "Derrick White", "BOS", "PG,SG", "G", ""],
    ["Nathan's Nifty Team", "Josh Hart", "NYK", "SG,SF", "SF", ""],
    ["Nathan's Nifty Team", "RJ Barrett", "TOR", "SG,SF,PF", "PF", ""],
    ["Nathan's Nifty Team", "Jalen Green", "PHX", "SG,SF", "F", ""],
    ["Nathan's Nifty Team", "Giannis Antetokounmpo", "MIA", "PF,C", "C", ""],
    ["Nathan's Nifty Team", "Ivica Zubac", "IND", "C", "C", ""],
    ["Nathan's Nifty Team", "VJ Edgecombe", "PHI", "PG,SG", "Util", ""],
    ["Nathan's Nifty Team", "Jared McCain", "OKC", "PG,SG", "Util", ""],
    ["Nathan's Nifty Team", "Daniss Jenkins", "DET", "PG,SG", "BN", ""],
    ["Nathan's Nifty Team", "Franz Wagner", "ORL", "SF,PF", "BN", ""],
    ["Nathan's Nifty Team", "Jeremiah Fears", "NOP", "PG,SG", "BN", ""],
    ["Nathan's Nifty Team", "Jusuf Nurkić", "UTA", "C", "IL", "O"],
    ["Nathan's Nifty Team", "Kon Knueppel", "CHA", "SG,SF", "IL", "O"],
    ["JJ's Official Team", "Andrew Nembhard", "IND", "PG,SG", "PG", "O"],
    ["JJ's Official Team", "Kyshawn George", "WAS", "SG,SF,PF", "SG", ""],
    ["JJ's Official Team", "Ty Jerome", "MEM", "PG,SG", "G", "O"],
    ["JJ's Official Team", "Paul George", "BOS", "SF,PF", "SF", ""],
    ["JJ's Official Team", "Karl-Anthony Towns", "NYK", "PF,C", "PF", ""],
    ["JJ's Official Team", "Aaron Wiggins", "ATL", "SG,SF", "F", ""],
    ["JJ's Official Team", "Day'Ron Sharpe", "BKN", "C", "C", ""],
    ["JJ's Official Team", "Myles Turner", "MIL", "C", "C", ""],
    ["JJ's Official Team", "Darius Garland", "LAC", "PG", "Util", ""],
    ["JJ's Official Team", "Cameron Johnson", "DEN", "SF,PF", "Util", ""],
    ["JJ's Official Team", "Norman Powell", "CHI", "SG,SF", "BN", ""],
    ["JJ's Official Team", "Desmond Bane", "ORL", "SG,SF", "BN", ""],
    ["JJ's Official Team", "Anthony Edwards", "MIN", "PG,SG", "IL", "O"],
    ["Barangay Ginebra San Miguel", "Ayo Dosunmu", "MIN", "PG,SG", "PG", ""],
    ["Barangay Ginebra San Miguel", "Ausar Thompson", "DET", "SG,SF,PF", "SG", ""],
    ["Barangay Ginebra San Miguel", "Cade Cunningham", "DET", "PG,SG", "G", ""],
    ["Barangay Ginebra San Miguel", "LeBron James", "PHI", "SF,PF", "SF", ""],
    ["Barangay Ginebra San Miguel", "Bobby Portis Jr.", "MIA", "PF,C", "PF", ""],
    ["Barangay Ginebra San Miguel", "OG Anunoby", "NYK", "SF,PF", "F", ""],
    ["Barangay Ginebra San Miguel", "Isaiah Hartenstein", "OKC", "C", "C", ""],
    ["Barangay Ginebra San Miguel", "Daniel Gafford", "DAL", "C", "C", ""],
    ["Barangay Ginebra San Miguel", "Kyrie Irving", "DAL", "PG,SG", "Util", "O"],
    ["Barangay Ginebra San Miguel", "Josh Giddey", "CHI", "PG,SG", "Util", ""],
    ["Barangay Ginebra San Miguel", "Jaime Jaquez Jr.", "MIL", "SG,SF,PF", "BN", ""],
    ["Barangay Ginebra San Miguel", "Domantas Sabonis", "SAC", "PF,C", "BN", ""],
    ["Barangay Ginebra San Miguel", "Stephon Castle", "SAS", "PG,SG", "BN", ""],
    ["Barangay Ginebra San Miguel", "Brandon Ingram", "LAC", "SG,SF,PF", "IL", "O"],
    ["Barangay Ginebra San Miguel", "T.J. McConnell", "IND", "PG", "IL", ""]
  ],
  Trades: [
    ["Nathan's Nifty Team", "Karl-Anthony Towns", "JJ's Official Team", "Derrick White, Devin Booker", "Pending vote"]
  ]
};

function stamp_(ss) {
  var info = ss.getSheetByName(INFO);
  if (!info) return;
  var now = new Date();
  info.getRange(INFO_STAMP_ROW, 2, 1, 2).setValues([[now.toISOString(), Utilities.formatDate(now, TZ, 'MMM d, yyyy h:mm a') + ' (Manila)']]);
}

/** Creates the Info tab if it is missing. An existing Info tab is left alone. */
function info_(ss) {
  var info = ss.getSheetByName(INFO);
  if (info) return info;
  info = ss.insertSheet(INFO);
  var rows = [
    ['UBE League Hub: league data', '', ''],
    ['Last pasted', '', ''],
    ['', '', ''],
    ['Tab', 'What to paste', ''],
    ['Scores', TABS.Scores.note, ''],
    ['Standings', TABS.Standings.note, ''],
    ['Rosters', TABS.Rosters.note, ''],
    ['Trades', TABS.Trades.note, ''],
    ['Good to know', 'In Standings, Rosters and Trades, a row that only says END marks the end. Rows below END are ignored (old pastes).', ''],
    ['Team number', 'Yahoo team name (use these names in the team columns)', '']
  ];
  for (var i = 0; i < TEAMS.length; i++) rows.push([String(i + 1), TEAMS[i], '']);
  info.getRange(1, 1, info.getMaxRows(), 3).setNumberFormat('@');
  info.getRange(1, 1, rows.length, 3).setValues(rows);
  info.getRange(1, 1, 1, 3).setFontWeight('bold');
  info.getRange(4, 1, 1, 3).setFontWeight('bold');
  info.getRange(INFO_TEAM_ROW - 1, 1, 1, 3).setFontWeight('bold');
  info.setFrozenRows(1);
  info.setColumnWidth(2, 620);
  stamp_(ss);
  return info;
}

/** Creates one league tab with the current hub data. A tab that already exists is left exactly as it is. */
function leagueTab_(ss, name, info) {
  var def = TABS[name];
  var n = def.head.length;
  var sh = ss.getSheetByName(name);
  if (sh) return sh;
  sh = ss.insertSheet(name);
  var rows = SEED_LEAGUE[name].slice();
  if (def.end) {
    var end = ['END'];
    while (end.length < n) end.push('');
    rows.push(end);
  }
  sh.getRange(1, 1, sh.getMaxRows(), n).setNumberFormat('@');
  sh.getRange(1, 1, 1, n).setValues([def.head]).setFontWeight('bold');
  if (rows.length) sh.getRange(2, 1, rows.length, n).setValues(rows);
  sh.setFrozenRows(1);
  var body = sh.getMaxRows() - 1;
  var teamRule = SpreadsheetApp.newDataValidation().requireValueInRange(info.getRange(INFO_TEAM_ROW, 2, TEAMS.length, 1), true).setAllowInvalid(true).build();
  for (var t = 0; t < def.teams.length; t++) sh.getRange(2, def.teams[t], body, 1).setDataValidation(teamRule);
  for (var col in def.lists) {
    var rule = SpreadsheetApp.newDataValidation().requireValueInList(def.lists[col], true).setAllowInvalid(true).build();
    sh.getRange(2, Number(col), body, 1).setDataValidation(rule);
  }
  var guards = sh.getProtections(SpreadsheetApp.ProtectionType.RANGE);
  var guarded = false;
  for (var g = 0; g < guards.length; g++) if (guards[g].getDescription() === HEADER_NOTE) guarded = true;
  if (!guarded) sh.getRange(1, 1, 1, n).protect().setDescription(HEADER_NOTE).setWarningOnly(true);
  return sh;
}

function setupLeague_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var info = info_(ss);
  for (var i = 0; i < LEAGUE_TABS.length; i++) leagueTab_(ss, LEAGUE_TABS[i], info);
}

function tabRows_(ss, name) {
  var sh = ss.getSheetByName(name);
  var head = TABS[name].head;
  var out = [];
  if (!sh || sh.getLastRow() < 2) return out;
  var values = sh.getRange(2, 1, sh.getLastRow() - 1, head.length).getDisplayValues();
  for (var i = 0; i < values.length; i++) {
    var row = {};
    var any = false;
    for (var c = 0; c < head.length; c++) {
      row[head[c]] = String(values[i][c] == null ? '' : values[i][c]).trim();
      if (row[head[c]]) any = true;
    }
    if (any) out.push(row);
  }
  return out;
}

/** What the hub's daily update reads: .../exec?tab=league */
function league_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var missing = [];
  for (var i = 0; i < LEAGUE_TABS.length; i++) if (!ss.getSheetByName(LEAGUE_TABS[i])) missing.push(LEAGUE_TABS[i]);
  if (missing.length) return { ok: false, error: 'missing tabs: ' + missing.join(', ') + '. Run setup in Apps Script' };
  var info = ss.getSheetByName(INFO);
  var updated = '';
  var teams = [];
  if (info) {
    updated = String(info.getRange(INFO_STAMP_ROW, 2).getDisplayValue() || '').trim();
    var list = info.getRange(INFO_TEAM_ROW, 1, TEAMS.length, 2).getDisplayValues();
    for (var t = 0; t < list.length; t++) {
      var id = String(list[t][0] || '').trim();
      var name = String(list[t][1] || '').trim();
      if (/^\d+$/.test(id) && name) teams.push({ team_id: id, name: name });
    }
  }
  if (!teams.length) for (var k = 0; k < TEAMS.length; k++) teams.push({ team_id: String(k + 1), name: TEAMS[k] });
  return { ok: true, updated: updated, teams: teams, scores: tabRows_(ss, 'Scores'), standings: tabRows_(ss, 'Standings'),
           rosters: tabRows_(ss, 'Rosters'), trades: tabRows_(ss, 'Trades') };
}

/** Runs by itself whenever someone edits the sheet: notes the time a league tab was last changed. */
function onEdit(e) {
  try {
    var sh = e && e.range && e.range.getSheet();
    if (!sh || !TABS[sh.getName()]) return;
    stamp_(sh.getParent());
  } catch (err) { /* never block an edit */ }
}

/* ---------- optional weekly reminder (off until you run enableReminder once) ---------- */
function weekOf_(date) {
  var day = Utilities.formatDate(date, TZ, 'yyyy-MM-dd');
  var days = Math.round((Date.parse(day + 'T00:00:00Z') - Date.parse(WEEK2_START + 'T00:00:00Z')) / 86400000);
  return days < 0 ? 1 : Math.floor(days / 7) + 2;
}

function weeklyReminder() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var week = weekOf_(new Date()) - 1; // the week that ended last Sunday
  if (week < 1 || week > LAST_WEEK) return;
  var rows = tabRows_(ss, 'Scores');
  for (var i = 0; i < rows.length; i++) {
    if (Number(rows[i].week) === week && rows[i].status.toLowerCase() === 'final') return;
  }
  var to = '';
  try { to = ss.getOwner().getEmail(); } catch (err) { to = ''; }
  if (!to) to = Session.getEffectiveUser().getEmail();
  if (!to) return;
  MailApp.sendEmail(to, 'Paste the weekly UBE update',
    'Week ' + week + ' has no Final scores in the sheet yet.\n\n' +
    '1. Paste the WEEKLY reporter prompt into Claude.\n' +
    '2. Paste its four blocks into the Scores, Standings, Rosters and Trades tabs.\n\n' +
    'Sheet: ' + ss.getUrl());
}

/** Run once by hand to get an email every Tuesday at 10 AM (Manila) when last week's Final scores are not in the sheet yet. */
function enableReminder() {
  disableReminder();
  ScriptApp.newTrigger('weeklyReminder').timeBased().onWeekDay(ScriptApp.WeekDay.TUESDAY).atHour(REMINDER_HOUR).inTimezone(TZ).create();
}

/** Run once by hand to stop the weekly email. */
function disableReminder() {
  var all = ScriptApp.getProjectTriggers();
  for (var i = 0; i < all.length; i++) {
    if (all[i].getHandlerFunction() === 'weeklyReminder') ScriptApp.deleteTrigger(all[i]);
  }
}
