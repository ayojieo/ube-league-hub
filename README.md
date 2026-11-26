# UBE League Hub

Self-updating hub for the UBE League (10-team, 9-category Yahoo fantasy basketball).

- Site: https://ayojieo.github.io/ube-league-hub
- League data (scores, standings, rosters, IL slots, pending trades) comes from a Google Sheet that you paste into once a week.
- Everything else (injuries, headlines, player stats, NBA schedule) updates itself every day at 2:30 PM Manila time. No AI involved.
- The page does all the math (category ranks, power rankings, playoff odds, matchup projections) in the browser.

Yahoo's Fantasy API is not available to us (Yahoo only offers it in the United States and Canada), so the hub never contacts Yahoo.

## How it works

| Part | What it does |
|---|---|
| `page.html` | The hub page, copied from the Claude hub. See `CHANGES.md`. |
| `shim.js`, `shim.css`, `index.html` | Let the page run on its own. |
| `data/*.json` | Everything the page shows. Rewritten by the daily update. |
| `scripts/update.py` | The daily update: league data from the Google Sheet, ESPN (injuries, headlines), Hashtagbasketball (player stats, Mondays), NBA schedule. |
| `.github/workflows/` | Runs the scripts: **Daily update** and **New season**. |
| `apps-script/Code.gs` | Goes into the Google Sheet that holds the Trade market and the league data tabs. |
| `docs/reporter-prompt.md` | The prompt to paste into Claude (with Flaim) to get the weekly tables for the sheet. |
| `config/league.json` | League settings. Edited once a year. |
| `config/site.json` | The Google Sheet web app link (Trade market and league data). |
| `config/display_names.json` | Names shown on the hub instead of Yahoo's (team 1 = Team Hali, team 4 = Team Luka). |

If one source fails, the others still update and the old data for the failed one is kept. If the Google Sheet cannot be read, the run is marked failed and GitHub emails you. Nothing else sends email.

## Setting up the sheet

1. Open the Google Sheet **UBE Trade Market** → **Extensions** → **Apps Script**.
2. Select all the code, delete it, paste `apps-script/Code.gs`, click **Save**.
3. Choose **setup** in the function list, click **Run**. If Google asks for permission: choose your account → **Advanced** → **Go to (project name)** → **Allow**.
4. Choose **loadCurrentData**, click **Run**. This fills the Scores, Standings, Rosters and Trades tabs with the league data written in the script (copied from the Claude hub when the script was made). The Trade market tab is not touched.
5. **Deploy** → **Manage deployments** → pencil icon → Version: **New version** → **Deploy**. The link stays the same.
6. Check the sheet: tabs **market**, **Info**, **Scores**, **Standings**, **Rosters**, **Trades**.

Running **setup** again is safe: it only creates tabs that are missing. **loadCurrentData** replaces the four league tabs' rows, so only run it when you mean to.

### What each tab means

| Tab | Columns | Notes |
|---|---|---|
| Scores | week, team_a, cats_a, cats_b, team_b, status | One row per matchup. cats = categories won. status = `Final` or `In progress`. Add new weeks below the old rows; if a matchup is listed twice, the lower row wins. |
| Standings | rank, team, w, l, t | All 10 teams. Total category wins, losses, ties. |
| Rosters | team, player, nba_team, pos, slot, status | Every rostered player. slot = Yahoo lineup slot; `IL` or `IL+` puts the player on the injured list. status = blank, `O`, `Q`, `GTD`, `DTD`, `INJ`, `SUSP`. |
| Trades | team_a, a_gets, team_b, b_gets, processes | Pending trades only. Player names with commas between them. |
| Info | | What to paste, the time a tab was last changed, and the Yahoo team names. |

- Team names in the sheet are the **Yahoo names** (listed on the Info tab). The hub turns them into its own names (`config/display_names.json`). The hub's names work too.
- If a team is renamed on Yahoo, change its name on the Info tab.
- In Standings, Rosters and Trades, a row that only says `END` marks the end. Rows below it are ignored.
- A week that is `Final` is never reopened. Its score can still be corrected with another `Final` row.
- The week being played is worked out from today's date. It shows as live even before any score is pasted.

### Weekly routine

1. **Tuesday morning** (Yahoo closes the week on Monday evening Manila time): open a Claude chat with the Flaim connector and paste the **WEEKLY** prompt from `docs/reporter-prompt.md`.
2. Paste the four tables into the four tabs (the same file says where to click).
3. Done. The 2:30 PM update picks it up. To see it sooner: **Actions** → **Daily update** → **Run workflow**.
4. After a trade, an add or a drop during the week: use the **QUICK** prompt (Rosters and Trades only).

The hub's footer shows "League data: Google Sheet · pasted (date)". If nothing is pasted for more than 8 days, a small banner says so.

### Reminder email (optional)

- Turn on: Apps Script → choose **enableReminder** → **Run**. Every Tuesday at 10 AM (Manila) the script emails you "Paste the weekly UBE update" with a link to the sheet, but only if last week's `Final` scores are not in the Scores tab yet.
- Turn off: choose **disableReminder** → **Run**.
- The email is sent from your own Google account to yourself. That is why Google lists one extra permission, "Send email as you", when you run **setup**. The script sends nothing unless you turn the reminder on.

## Day to day

- **Edit a nickname or description:** open `data/managers.json` → pencil → change the `tagline` (nickname) or `summary` (description) text → commit. The update never changes them; it only refreshes the green and red pills and the power rank.
- **Run an update now:** Actions → Daily update → Run workflow.
- **Refresh stats or schedules now:** same, and type `htb` or `schedule` (or `htb,schedule`) in the box.
- **A run failed:** open it and read the summary. Most failures fix themselves on the next run.

### Problems in the run summary

| Message | What to do |
|---|---|
| Google Sheet: ... still the old version | Do "Setting up the sheet", steps 2 to 5. |
| Google Sheet: ... missing tabs | Apps Script → run **setup**. |
| Google Sheet: HTTP ... / did not send data | Check the deployment: Execute as **Me**, access **Anyone**. Check `market_url` in `config/site.json`. |
| unknown team "..." (row skipped) | Fix the name in that row. Valid names are on the Info tab. |
| the two scores must be whole numbers that add up to 9 or less | Fix cats_a and cats_b in that row. |
| ... is not a matchup on the schedule for that week | Wrong week number or wrong teams in that row. |
| ... is already Final | A row tried to reopen a finished week. Delete that row, or mark it `Final`. |
| Standings: ... Kept the previous standings | The Standings tab needs all 10 teams, each once, each with its own rank. |
| ... is on two teams | The player is in two teams' rows. Delete the wrong row. |
| ... has 19 players (the most a team can hold is 18) | An old paste is left below the new one. Delete the extra rows or add an `END` row. |
| Rosters tab is empty. Kept the current rosters | Paste the Rosters block again. |
| No stats found yet for: (player) | A new player outside Hashtagbasketball's top 200. He counts at the minimum value until he is listed. |

Bad rows are skipped and the hub keeps what it had for them. The run fails (and GitHub emails you) only when the sheet cannot be read at all.
| Hashtagbasketball ... | Their page changed or blocked the request. Last week's stats stay. If it repeats for weeks, the reader in `scripts/hub/sources.py` needs an update. |
| NBA schedule failed | The old schedule stays. Matchup falls back to per-game averages for weeks with no schedule. |
| A player from another site is not matched | Add the two spellings to `config/aliases.json` (their spelling: Yahoo's spelling). |

## Each new season

1. When the season ends, the update saves the final hub under `archive/<season>/`, clears the live data and pauses.
2. When the new Yahoo league exists (after the draft):
   - Edit `config/league.json`: `season`, `week1_start`, `week2_start`, `season_end`, `trade_deadline`, `rivalry_weeks`, `playoff_weeks`, and `managers` (Yahoo team number: name).
   - In `docs/reporter-prompt.md`, change `league_id` and `season_year` in both prompts (Flaim shows the new league id).
   - In `apps-script/Code.gs` (and the copy in Apps Script), change `WEEK2_START`. On the sheet's Info tab, update the team names.
3. Fill the sheet for the new league: the Rosters tab, and in the Scores tab every week's pairings (one row per matchup, scores empty, status `Not started`). Ask Claude with Flaim for "every week's matchups, weeks 1 to 19, as the Scores table". Clear the old Standings and Trades rows (leave the header and an `END` row).
4. Actions → **New season** → Run workflow.
5. If the Daily update shows as disabled (GitHub pauses schedules after 60 quiet days): Actions → Daily update → **Enable workflow**.
6. In `page.html`, the Season line on the Overview tab (trade deadline, playoff dates, prize pool) is plain text. Edit it by hand if those change.

## Good to know

- **Pending trades:** Flaim shows the pending trades Yahoo lets your account see. If a trade is missing, type it into the Trades tab by hand, above the `END` line.
- **Team renamed on Yahoo:** change its name on the sheet's Info tab. The hub follows the new name everywhere. That team's Trade market row starts empty under the new name.
- **Weekly Slate dates:** the page assumes every week is Monday to Sunday. If Yahoo runs one long week (All-Star break), the dates shown for later weeks drift. The Matchup tab is not affected.
- **Checking the scripts:** `python3 tests/run_tests.py` runs the update against made-up answers. `node tests/code_gs_test.js` does the same for the sheet's script. They need Python 3.9+ and Node, and use the frozen data in `tests/fixtures`.

Data comes from Yahoo Fantasy (pasted into the Google Sheet), ESPN, Hashtag Basketball and the NBA schedule. This is a private league tool, not affiliated with any of them.
