/**
 * UBE League Hub: Google Sheet script (Extensions > Apps Script).
 *
 * 1. Trade market (tab "market")
 *    - Anyone can read the entries (the hub page shows them).
 *    - Saving needs the passcode. Set it in Project Settings > Script Properties: name PASSCODE.
 *      The passcode is never written in this file.
 * 2. League data (tabs Scores, Standings, Rosters, Trades, Info)
 *    - The hub's only source for scores, standings, rosters, IL slots and pending trades (pasted here from Yahoo).
 *    - Anyone can read them (same data the public hub shows). Only people who can edit the sheet can change them.
 *
 * After changing this file: Save, Run > setup, then Deploy > Manage deployments > pencil > Version: New version > Deploy.
 * The web app link stays the same.
 * To replace the league tabs with the current data written below (SEED_LEAGUE): Run > loadCurrentData (once).
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
 * The hub's daily update reads them every day (its only league data source).
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
  Scores: { head: ['week', 'team_a', 'cats_a', 'cats_b', 'team_b', 'status'], teams: [2, 5], lists: { 6: ['Final', 'In progress', 'Not started'] }, end: false,
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
var SEED_LEAGUE = { // current league data (Claude hub, Nov 26 2026). Used by setup (new tabs) and loadCurrentData.
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
    ["4", "Jayden's Amazing Team", "6", "3", "Barangay Ginebra San Miguel", "Final"],
    ["5", "The Haliban", "4", "5", "JJ's Official Team", "Final"],
    ["5", "Yaxel and Em", "5", "4", "Barangay Ginebra San Miguel", "Final"],
    ["5", "Paulo's Perfect Team", "8", "1", "Nathan's Nifty Team", "Final"],
    ["5", "Master Luka’s Cotton Pickers", "3", "5", "Jayden's Amazing Team", "Final"],
    ["5", "DAVRAA Boys", "5", "4", "Nathaniel's Notable Team", "Final"],
    ["6", "The Haliban", "3", "6", "DAVRAA Boys", "In progress"],
    ["6", "Yaxel and Em", "5", "4", "Master Luka’s Cotton Pickers", "In progress"],
    ["6", "Paulo's Perfect Team", "3", "6", "Nathaniel's Notable Team", "In progress"],
    ["6", "Jayden's Amazing Team", "8", "1", "Nathan's Nifty Team", "In progress"],
    ["6", "JJ's Official Team", "6", "3", "Barangay Ginebra San Miguel", "In progress"]
  ],
  Standings: [
    ["1", "DAVRAA Boys", "29", "15", "1"],
    ["2", "Jayden's Amazing Team", "28", "16", "1"],
    ["3", "Paulo's Perfect Team", "27", "18", "0"],
    ["4", "Barangay Ginebra San Miguel", "24", "21", "0"],
    ["5", "Yaxel and Em", "23", "21", "1"],
    ["6", "Nathaniel's Notable Team", "23", "22", "0"],
    ["7", "Master Luka’s Cotton Pickers", "21", "22", "2"],
    ["8", "The Haliban", "21", "24", "0"],
    ["9", "JJ's Official Team", "17", "27", "1"],
    ["10", "Nathan's Nifty Team", "9", "36", "0"]
  ],
  Rosters: [
    ["The Haliban", "Amen Thompson", "HOU", "PG,SG", "BN", ""],
    ["The Haliban", "Dyson Daniels", "ATL", "SG,SF", "BN", ""],
    ["The Haliban", "Nickeil Alexander-Walker", "ATL", "PG,SG", "BN", ""],
    ["The Haliban", "Toumani Camara", "POR", "SF,PF", "BN", ""],
    ["The Haliban", "Michael Porter Jr.", "BKN", "SF,PF", "BN", ""],
    ["The Haliban", "Collin Murray-Boyles", "TOR", "PF,C", "BN", ""],
    ["The Haliban", "Donovan Clingan", "POR", "C", "BN", ""],
    ["The Haliban", "Charles Bassey", "GSW", "C", "BN", ""],
    ["The Haliban", "Trey Murphy III", "NOP", "SG,SF", "BN", ""],
    ["The Haliban", "Kris Dunn", "LAC", "PG,SG", "BN", ""],
    ["The Haliban", "Yves Missi", "NOP", "C", "BN", ""],
    ["The Haliban", "AJ Dybantsa", "WAS", "SF", "BN", ""],
    ["The Haliban", "Jalen Johnson", "ATL", "SF,PF", "BN", ""],
    ["The Haliban", "Aday Mara", "OKC", "C", "IL", "O"],
    ["The Haliban", "Tyrese Haliburton", "IND", "PG,SG", "IL", "O"],
    ["The Haliban", "Jalen Duren", "DET", "C", "IL", "O"],
    ["The Haliban", "Mark Williams", "PHX", "C", "IL", "O"],
    ["Yaxel and Em", "Darius Garland", "LAC", "PG", "BN", ""],
    ["Yaxel and Em", "Cedric Coward", "MEM", "SG,SF", "BN", ""],
    ["Yaxel and Em", "Tyrese Maxey", "PHI", "PG", "BN", ""],
    ["Yaxel and Em", "Matas Buzelis", "CHI", "SF,PF", "BN", ""],
    ["Yaxel and Em", "Yaxel Lendeborg", "GSW", "SF,PF", "BN", ""],
    ["Yaxel and Em", "Peyton Watson", "CLE", "SF,PF", "BN", ""],
    ["Yaxel and Em", "Alperen Şengün", "HOU", "PF,C", "BN", ""],
    ["Yaxel and Em", "Neemias Queta", "BOS", "C", "BN", ""],
    ["Yaxel and Em", "Naz Reid", "CHA", "PF,C", "BN", ""],
    ["Yaxel and Em", "Coby White", "CHA", "PG,SG", "BN", ""],
    ["Yaxel and Em", "Desmond Bane", "ORL", "SG,SF", "BN", ""],
    ["Yaxel and Em", "Saddiq Bey", "NOP", "SF,PF", "BN", ""],
    ["Yaxel and Em", "Onyeka Okongwu", "ATL", "C", "BN", ""],
    ["Yaxel and Em", "Duncan Robinson", "DET", "SG,SF", "IL", "O"],
    ["Yaxel and Em", "Evan Mobley", "CLE", "PF,C", "IL", "O"],
    ["Paulo's Perfect Team", "Jamal Murray", "DEN", "PG", "BN", ""],
    ["Paulo's Perfect Team", "Collin Gillespie", "PHX", "PG,SG", "BN", ""],
    ["Paulo's Perfect Team", "Kevin Porter Jr.", "ORL", "PG,SG", "BN", ""],
    ["Paulo's Perfect Team", "Klay Thompson", "MIA", "SG,SF", "BN", ""],
    ["Paulo's Perfect Team", "Jabari Smith Jr.", "HOU", "PF,C", "BN", ""],
    ["Paulo's Perfect Team", "Ace Bailey", "UTA", "SF,PF", "BN", ""],
    ["Paulo's Perfect Team", "Brook Lopez", "LAC", "C", "BN", ""],
    ["Paulo's Perfect Team", "Nikola Jokić", "DEN", "C", "BN", ""],
    ["Paulo's Perfect Team", "Jarrett Allen", "CLE", "C", "BN", ""],
    ["Paulo's Perfect Team", "Mikel Brown Jr.", "BKN", "PG", "BN", ""],
    ["Paulo's Perfect Team", "Immanuel Quickley", "TOR", "PG,SG", "BN", ""],
    ["Paulo's Perfect Team", "Keyonte George", "UTA", "PG,SG", "BN", ""],
    ["Paulo's Perfect Team", "Anthony Davis", "WAS", "PF,C", "BN", ""],
    ["Paulo's Perfect Team", "Cameron Boozer", "MEM", "PF,C", "IL", "O"],
    ["Paulo's Perfect Team", "Kawhi Leonard", "TOR", "SG,SF,PF", "IL", "O"],
    ["Master Luka’s Cotton Pickers", "Trae Young", "WAS", "PG", "BN", ""],
    ["Master Luka’s Cotton Pickers", "Donovan Mitchell", "CLE", "PG,SG", "BN", ""],
    ["Master Luka’s Cotton Pickers", "Darius Acuff Jr.", "SAC", "PG", "BN", ""],
    ["Master Luka’s Cotton Pickers", "Jayson Tatum", "BOS", "SF,PF", "BN", ""],
    ["Master Luka’s Cotton Pickers", "Tari Eason", "HOU", "SG,SF,PF", "BN", ""],
    ["Master Luka’s Cotton Pickers", "De'Andre Hunter", "SAC", "SF,PF", "BN", ""],
    ["Master Luka’s Cotton Pickers", "Rudy Gobert", "MIN", "C", "BN", ""],
    ["Master Luka’s Cotton Pickers", "Zach Edey", "MEM", "C", "BN", "Q"],
    ["Master Luka’s Cotton Pickers", "Jakob Poeltl", "TOR", "C", "BN", ""],
    ["Master Luka’s Cotton Pickers", "Darryn Peterson", "UTA", "PG,SG", "BN", ""],
    ["Master Luka’s Cotton Pickers", "Alex Sarr", "WAS", "C", "BN", ""],
    ["Master Luka’s Cotton Pickers", "Luka Dončić", "LAL", "PG,SG", "BN", ""],
    ["Master Luka’s Cotton Pickers", "Quentin Grimes", "LAL", "SG,SF", "BN", ""],
    ["Master Luka’s Cotton Pickers", "Jalen Smith", "CHI", "PF,C", "IL", "O"],
    ["Master Luka’s Cotton Pickers", "Lauri Markkanen", "UTA", "SF,PF", "IL", "O"],
    ["Master Luka’s Cotton Pickers", "Caleb Wilson", "CHI", "PF", "IL", "O"],
    ["Master Luka’s Cotton Pickers", "Paolo Banchero", "ORL", "PF", "IL", "O"],
    ["DAVRAA Boys", "Jrue Holiday", "POR", "PG,SG", "BN", ""],
    ["DAVRAA Boys", "Cam Spencer", "MEM", "PG,SG", "BN", ""],
    ["DAVRAA Boys", "Kevin Durant", "HOU", "SG,SF,PF", "BN", ""],
    ["DAVRAA Boys", "Jonathan Kuminga", "MIN", "SF,PF", "BN", ""],
    ["DAVRAA Boys", "Zion Williamson", "NOP", "PF,C", "BN", ""],
    ["DAVRAA Boys", "Miles Bridges", "PHX", "PF", "BN", ""],
    ["DAVRAA Boys", "Paul Reed", "DET", "PF,C", "BN", ""],
    ["DAVRAA Boys", "P.J. Washington", "DAL", "PF,C", "BN", ""],
    ["DAVRAA Boys", "Walker Kessler", "LAL", "C", "BN", ""],
    ["DAVRAA Boys", "Buddy Hield", "CHI", "SG,SF", "BN", ""],
    ["DAVRAA Boys", "Derik Queen", "NOP", "PF,C", "BN", ""],
    ["DAVRAA Boys", "Payton Pritchard", "BOS", "PG", "BN", ""],
    ["DAVRAA Boys", "Cooper Flagg", "DAL", "SG,SF,PF", "BN", ""],
    ["DAVRAA Boys", "Joel Embiid", "PHI", "C", "IL", "O"],
    ["DAVRAA Boys", "Austin Reaves", "LAL", "PG,SG,SF", "IL", "O"],
    ["DAVRAA Boys", "Stephen Curry", "GSW", "PG", "IL", "O"],
    ["DAVRAA Boys", "Ja Morant", "POR", "PG", "IL", "O"],
    ["DAVRAA Boys", "Jaren Jackson Jr.", "UTA", "PF,C", "IL", "O"],
    ["Nathaniel's Notable Team", "Ajay Mitchell", "OKC", "PG,SG", "BN", ""],
    ["Nathaniel's Notable Team", "James Harden", "CLE", "PG,SG", "BN", ""],
    ["Nathaniel's Notable Team", "De'Aaron Fox", "SAS", "PG", "BN", "O"],
    ["Nathaniel's Notable Team", "Zach LaVine", "SAC", "PG,SG,SF", "BN", "O"],
    ["Nathaniel's Notable Team", "Julius Randle", "BKN", "PF", "BN", ""],
    ["Nathaniel's Notable Team", "Brandon Miller", "CHA", "SF,PF", "BN", ""],
    ["Nathaniel's Notable Team", "Victor Wembanyama", "SAS", "C", "BN", ""],
    ["Nathaniel's Notable Team", "Giannis Antetokounmpo", "MIA", "PF,C", "BN", ""],
    ["Nathaniel's Notable Team", "Damian Lillard", "POR", "PG", "BN", ""],
    ["Nathaniel's Notable Team", "LaMelo Ball", "MIN", "PG", "BN", "Q"],
    ["Nathaniel's Notable Team", "Aaron Gordon", "DEN", "PF,C", "BN", ""],
    ["Nathaniel's Notable Team", "Pascal Siakam", "IND", "PF,C", "BN", ""],
    ["Nathaniel's Notable Team", "Isaiah Joe", "DET", "SG,SF", "BN", ""],
    ["Jayden's Amazing Team", "Fred VanVleet", "HOU", "PG", "BN", ""],
    ["Jayden's Amazing Team", "Tyler Herro", "MIL", "PG,SG", "BN", ""],
    ["Jayden's Amazing Team", "Shai Gilgeous-Alexander", "OKC", "PG", "BN", ""],
    ["Jayden's Amazing Team", "Julian Champagnie", "SAS", "SF,PF", "BN", ""],
    ["Jayden's Amazing Team", "Bam Adebayo", "MIA", "PF,C", "BN", ""],
    ["Jayden's Amazing Team", "Jaden McDaniels", "MIN", "SF", "BN", ""],
    ["Jayden's Amazing Team", "Scottie Barnes", "TOR", "SF,PF,C", "BN", ""],
    ["Jayden's Amazing Team", "Moussa Diabaté", "CHA", "C", "BN", ""],
    ["Jayden's Amazing Team", "Brandin Podziemski", "GSW", "PG,SG", "BN", ""],
    ["Jayden's Amazing Team", "Davion Mitchell", "MIA", "PG", "BN", ""],
    ["Jayden's Amazing Team", "Wendell Carter Jr.", "ORL", "C", "BN", ""],
    ["Jayden's Amazing Team", "Anthony Black", "ORL", "PG,SG,SF", "BN", ""],
    ["Jayden's Amazing Team", "Christian Braun", "DEN", "SG,SF,PF", "BN", ""],
    ["Jayden's Amazing Team", "Dejounte Murray", "NOP", "PG,SG", "IL", "O"],
    ["Jayden's Amazing Team", "Jimmy Butler III", "GSW", "SF,PF", "IL", "O"],
    ["Jayden's Amazing Team", "Chet Holmgren", "OKC", "PF,C", "IL", "O"],
    ["Nathan's Nifty Team", "VJ Edgecombe", "PHI", "PG,SG", "BN", ""],
    ["Nathan's Nifty Team", "Brayden Burries", "MIL", "SG", "BN", ""],
    ["Nathan's Nifty Team", "Jaylen Brown", "PHI", "SG,SF,PF", "BN", "O"],
    ["Nathan's Nifty Team", "Josh Hart", "NYK", "SG,SF", "BN", ""],
    ["Nathan's Nifty Team", "Deni Avdija", "POR", "SG,SF,PF", "BN", ""],
    ["Nathan's Nifty Team", "Jalen Green", "PHX", "SG,SF", "BN", ""],
    ["Nathan's Nifty Team", "Karl-Anthony Towns", "NYK", "PF,C", "BN", ""],
    ["Nathan's Nifty Team", "Ivica Zubac", "IND", "C", "BN", ""],
    ["Nathan's Nifty Team", "Jared McCain", "OKC", "PG,SG", "BN", ""],
    ["Nathan's Nifty Team", "Landry Shamet", "NYK", "SG,SF", "BN", ""],
    ["Nathan's Nifty Team", "Jeremiah Fears", "NOP", "PG,SG", "BN", ""],
    ["Nathan's Nifty Team", "Franz Wagner", "ORL", "SF,PF", "BN", ""],
    ["Nathan's Nifty Team", "Daniss Jenkins", "DET", "PG,SG", "BN", ""],
    ["Nathan's Nifty Team", "RJ Barrett", "TOR", "SG,SF,PF", "IL", "O"],
    ["Nathan's Nifty Team", "Dylan Harper", "SAS", "PG,SG,SF", "IL", "O"],
    ["Nathan's Nifty Team", "Jusuf Nurkić", "UTA", "C", "IL", "O"],
    ["Nathan's Nifty Team", "Kon Knueppel", "CHA", "SG,SF", "IL", "O"],
    ["JJ's Official Team", "Ty Jerome", "MEM", "PG,SG", "BN", ""],
    ["JJ's Official Team", "Devin Booker", "PHX", "PG,SG", "BN", ""],
    ["JJ's Official Team", "Jalen Brunson", "NYK", "PG", "BN", ""],
    ["JJ's Official Team", "Keegan Murray", "SAC", "SF,PF", "BN", ""],
    ["JJ's Official Team", "Mikal Bridges", "NYK", "SF,PF", "BN", ""],
    ["JJ's Official Team", "Paul George", "BOS", "SF,PF", "BN", ""],
    ["JJ's Official Team", "Day'Ron Sharpe", "BKN", "C", "BN", ""],
    ["JJ's Official Team", "Myles Turner", "MIL", "C", "BN", ""],
    ["JJ's Official Team", "Devin Vassell", "SAS", "SG,SF", "BN", ""],
    ["JJ's Official Team", "Tre Jones", "CHI", "PG,SG", "BN", ""],
    ["JJ's Official Team", "Kyshawn George", "WAS", "SG,SF,PF", "BN", ""],
    ["JJ's Official Team", "Derrick White", "BOS", "PG,SG", "BN", ""],
    ["JJ's Official Team", "Andrew Nembhard", "IND", "PG,SG", "BN", ""],
    ["JJ's Official Team", "Norman Powell", "CHI", "SG,SF", "IL", "O"],
    ["JJ's Official Team", "Jerami Grant", "MEM", "SF,PF", "IL", "O"],
    ["JJ's Official Team", "Anthony Edwards", "MIN", "PG,SG", "IL", "O"],
    ["Barangay Ginebra San Miguel", "Ayo Dosunmu", "MIN", "PG,SG", "BN", ""],
    ["Barangay Ginebra San Miguel", "Stephon Castle", "SAS", "PG,SG", "BN", ""],
    ["Barangay Ginebra San Miguel", "Brandon Ingram", "LAC", "SG,SF,PF", "BN", ""],
    ["Barangay Ginebra San Miguel", "LeBron James", "PHI", "SF,PF", "BN", ""],
    ["Barangay Ginebra San Miguel", "Bobby Portis Jr.", "MIA", "PF,C", "BN", ""],
    ["Barangay Ginebra San Miguel", "Pelle Larsson", "MIA", "SG,SF", "BN", ""],
    ["Barangay Ginebra San Miguel", "Domantas Sabonis", "SAC", "PF,C", "BN", ""],
    ["Barangay Ginebra San Miguel", "Isaiah Hartenstein", "OKC", "C", "BN", ""],
    ["Barangay Ginebra San Miguel", "Josh Giddey", "CHI", "PG,SG", "BN", ""],
    ["Barangay Ginebra San Miguel", "Jaime Jaquez Jr.", "MIL", "SG,SF,PF", "BN", ""],
    ["Barangay Ginebra San Miguel", "Ausar Thompson", "DET", "SG,SF,PF", "BN", ""],
    ["Barangay Ginebra San Miguel", "Kyrie Irving", "DAL", "PG,SG", "BN", ""],
    ["Barangay Ginebra San Miguel", "Daniel Gafford", "DAL", "C", "BN", ""],
    ["Barangay Ginebra San Miguel", "Cade Cunningham", "DET", "PG,SG", "IL", "Q"],
    ["Barangay Ginebra San Miguel", "OG Anunoby", "NYK", "SF,PF", "IL", "O"],
    ["Barangay Ginebra San Miguel", "Grayson Allen", "CHA", "SG,SF", "IL", "O"]
  ],
  Trades: [
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

/** Run by hand (Run > loadCurrentData) to replace the Scores, Standings, Rosters and Trades rows with SEED_LEAGUE above.
 *  Headers, dropdowns and the Info tab stay. Use it once after pasting a new version of this file; after that, paste
 *  the reporter's tables as usual. */
function loadCurrentData() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var info = info_(ss);
  for (var i = 0; i < LEAGUE_TABS.length; i++) {
    var name = LEAGUE_TABS[i];
    var def = TABS[name];
    var n = def.head.length;
    var sh = leagueTab_(ss, name, info);
    var rows = SEED_LEAGUE[name].slice();
    if (def.end) {
      var end = ['END'];
      while (end.length < n) end.push('');
      rows.push(end);
    }
    if (sh.getLastRow() > 1) sh.getRange(2, 1, sh.getLastRow() - 1, Math.max(n, sh.getLastColumn())).clearContent();
    sh.getRange(1, 1, sh.getMaxRows(), n).setNumberFormat('@');
    if (rows.length) sh.getRange(2, 1, rows.length, n).setValues(rows);
  }
  stamp_(ss);
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
