# UBE League Hub

Self-updating hub for the UBE League (10-team, 9-category Yahoo fantasy basketball).

- Site: https://ayojieo.github.io/ube-league-hub
- Updates itself every day at 2:30 PM Manila time. No AI involved.
- The page does all the math (category ranks, power rankings, playoff odds, matchup projections) in the browser.

## How it works

| Part | What it does |
|---|---|
| `page.html` | The hub page, copied from the Claude hub. See `CHANGES.md`. |
| `shim.js`, `shim.css`, `index.html` | Let the page run on its own. |
| `data/*.json` | Everything the page shows. Rewritten by the daily update. |
| `scripts/update.py` | The daily update: Yahoo (scores, standings, rosters, IL slots, pending trades), ESPN (injuries, headlines), Hashtagbasketball (player stats, Mondays), NBA schedule. |
| `.github/workflows/` | Runs the scripts: **Daily update**, **Yahoo login**, **New season**. |
| `apps-script/Code.gs` | Goes into the Google Sheet that stores the Trade market. |
| `config/league.json` | League settings. Edited once a year. |
| `config/site.json` | The Trade market link. |

If one source fails, the others still update and the old data for the failed one is kept. If Yahoo fails, the run is marked failed and GitHub emails you.

## First-time setup

### 1. Upload the files

1. Unzip `ube-league-hub.zip` on your computer.
2. Open the unzipped folder. You should see `index.html`, `data`, `scripts`, `.github` and more.
   - On a Mac, `.github` is hidden. Press **Cmd + Shift + .** in Finder to show it.
3. On GitHub, open the repository → **Add file** → **Upload files**.
4. Select everything inside the folder and drag it into the upload box. Wait until all files are listed.
5. Click **Commit changes**.
6. Check: the repository now shows a `.github/workflows` folder with three files. If it is missing, create each file by hand: **Add file** → **Create new file**, type the name `.github/workflows/daily.yml`, paste the file's content, commit. Repeat for `yahoo-login.yml` and `new-season.yml`.

### 2. Turn on the site

1. **Settings** → **Pages**.
2. Source: **Deploy from a branch**. Branch: **main**, folder **/ (root)**. Click **Save**.
3. Wait about a minute, then open https://ayojieo.github.io/ube-league-hub. The hub shows the starting data.

### 3. Trade market (Google Sheet)

1. Open your blank Google Sheet **UBE Trade Market**.
2. **Extensions** → **Apps Script**. Delete the sample code.
3. Open `apps-script/Code.gs` in this repository, copy all of it, paste it into the editor, click **Save**.
4. Left side: **Project Settings** (gear) → **Script Properties** → **Add script property**. Property: `PASSCODE`. Value: your passcode. **Save script properties**.
5. Back to **Editor**. In the function list at the top choose **setup**, click **Run**. Google asks for permission: choose your account → **Advanced** → **Go to (project name)** → **Allow**. A tab named `market` appears in the sheet with all 10 teams.
6. **Deploy** → **New deployment** → gear icon → **Web app**. Execute as: **Me**. Who has access: **Anyone**. Click **Deploy**.
7. Copy the **Web app URL** (it ends with `/exec`).
8. On GitHub open `config/site.json` → pencil icon → paste the URL between the quotes so it reads `"market_url": "https://script.google.com/macros/s/.../exec"` → **Commit changes**.

Only people with the passcode can save. To change the passcode, change the `PASSCODE` property. If you change the script later, use **Deploy** → **Manage deployments** → edit → **New version**, so the link stays the same.

### 4. Yahoo login (one time)

1. Open https://ayojieo.github.io/ube-league-hub/setup.html
2. Paste your Yahoo **Client ID**, click **Open Yahoo and click Agree**.
3. The browser lands on a page that cannot load (`https://localhost:8080/?code=...`). That is expected. Copy the whole address, paste it into step 2 of the setup page, click **Copy code**.
4. Click **Open the Yahoo login workflow** → **Run workflow** → paste the code → **Run workflow**.
5. Do steps 3 and 4 within a few minutes. The code expires quickly and works once. If the run fails, start again from step 2.
6. A green check means the key is saved as the secret `YAHOO_REFRESH_TOKEN`.

### 5. First update

1. **Actions** → **Daily update** → **Run workflow** → **Run workflow**.
2. Open the run when it finishes. The summary lists what changed and any problems.
3. Refresh the site after a minute.

From here it runs by itself every day.

## Day to day

- **Edit a tagline:** open `data/managers.json` → pencil → change the `tagline` text → commit. The update never changes taglines.
- **Run an update now:** Actions → Daily update → Run workflow.
- **Refresh stats or schedules now:** same, and type `htb` or `schedule` (or `htb,schedule`) in the box.
- **A run failed:** open it and read the summary. Most failures fix themselves on the next run.

| Problem in the summary | What to do |
|---|---|
| Yahoo sign-in failed | Do "Yahoo login" again (step 4). |
| Hashtagbasketball ... | Their page changed or blocked the request. Last week's stats stay. If it repeats for weeks, the reader in `scripts/hub/sources.py` needs an update. |
| NBA schedule failed | The old schedule stays. Matchup falls back to per-game averages for weeks with no schedule. |
| No stats found yet for: (player) | A new player nobody lists yet. Fixed by the next Monday refresh. |
| A player from another site is not matched | Add the two spellings to `config/aliases.json` (their spelling: Yahoo's spelling). |

## Each new season

1. Before May 1, 2027: make a new GitHub token (same settings as before) and replace the `GH_PAT` secret.
2. When the season ends, the update saves the final hub under `archive/<season>/`, clears the live data and pauses.
3. When the new Yahoo league exists (after the draft): edit `config/league.json`
   - `league_key`: the new one. It looks like `478.l.211732`: the number after `l.` is in your league's web address, the first number changes every season (the New season run fails with a clear message if it is wrong).
   - `season`, `week1_start`, `week2_start`, `season_end`, `trade_deadline`, `rivalry_weeks`, `playoff_weeks`, and `managers` (Yahoo team number: name).
4. Actions → **New season** → Run workflow.
5. If the Daily update shows as disabled (GitHub pauses schedules after 60 quiet days): Actions → Daily update → **Enable workflow**.
6. In `page.html`, the Season line on the Overview tab (trade deadline, playoff dates, prize pool) is plain text. Edit it by hand if those change.

## Good to know

- **Pending trades:** Yahoo's data feed shows accepted trades waiting for the league vote. Private offers are never shown. If Yahoo only returns trades that involve your team, other teams' pending trades will not appear here.
- **Team renamed on Yahoo:** the hub follows the new name everywhere. That team's Trade market row starts empty under the new name.
- **Weekly Slate dates:** the page assumes every week is Monday to Sunday. If Yahoo runs one long week (All-Star break), the dates shown for later weeks drift. The Matchup tab is not affected.
- **Checking the scripts:** `python3 tests/run_tests.py` runs the update against made-up answers. It needs Python 3.9+ and Node.

Data comes from Yahoo Fantasy, ESPN, Hashtag Basketball and the NBA schedule. This is a private league tool, not affiliated with any of them.
