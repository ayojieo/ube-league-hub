// Runs the page's own ranking model (UBE_RANK in page.html) so the scripts and the page always agree.
// Usage: node scripts/rank.js [dataDir]  -> prints {"profiles": [...], "power": [...]}
const fs = require('fs');
const path = require('path');
const root = process.env.UBE_ROOT || path.resolve(__dirname, '..');
const dataDir = process.argv[2] ? path.resolve(process.argv[2]) : path.join(root, 'data');
const page = fs.readFileSync(path.join(root, 'page.html'), 'utf8');
const start = page.indexOf('const UBE_RANK = (() => {');
const end = page.indexOf('window.UBE_RANK = UBE_RANK;');
if (start < 0 || end < start) { console.error('UBE_RANK model not found in page.html'); process.exit(2); }
const UBE_RANK = new Function(page.slice(start, end) + '\nreturn UBE_RANK;')();
const read = (name) => JSON.parse(fs.readFileSync(path.join(dataDir, name + '.json'), 'utf8'));
const players = read('players');
process.stdout.write(JSON.stringify({ profiles: UBE_RANK.profiles(players), power: UBE_RANK.power(players, read('schedule'), read('standings')) }));
