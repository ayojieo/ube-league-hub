# Reporter prompt (for a Claude chat with the Flaim connector)

Use this when the hub gets its league data from the Google Sheet (`config/sources.json` says `"sheet"`).
Open a new Claude chat that has the **Flaim** connector on, paste one of the two prompts below, and wait for the blocks.
A smaller model is fine.

- **WEEKLY**: all four tabs. Use it every **Tuesday morning** (Manila time). Yahoo closes the week on Monday evening Manila time; before that the last week still shows as In progress and the standings do not count it yet.
- **QUICK**: Rosters and Trades only. Use it after a trade, an add or a drop.

## Pasting the blocks into the sheet

Each block has a **Copy** button at its top right corner.

| Block | Where to paste |
|---|---|
| Scores | Open the **Scores** tab. Click the first empty cell in column A, below the old rows. Press **Ctrl+V**. |
| Standings | Open the **Standings** tab. Click cell **A1**. Press **Ctrl+V**. |
| Rosters | Open the **Rosters** tab. Click cell **A1**. Press **Ctrl+V**. |
| Trades | Open the **Trades** tab. Click cell **A1**. Press **Ctrl+V**. |

- If Google Sheets says the header row is protected, click **OK**. That is expected.
- Each value must land in its own column. If a whole line sits in column A, press Ctrl+Z and ask Claude: "Send the blocks again with real tab characters."
- Old rows left below a line that says `END` are ignored. You do not need to delete them.
- The hub picks the paste up at the next daily update (2:30 PM Manila). To see it now: GitHub → **Actions** → **Daily update** → **Run workflow**.

## WEEKLY prompt

````text
You are the reporter for the UBE League Hub. Use only the Flaim connector. Do not use memory or the web. Do not give advice.

League: platform "yahoo", sport "basketball", league_id "478.l.211732", season_year 2026. The teams have team_id 1 to 10.

Do these calls in this order:
1. get_league_info. Note currentWeek (call it C) and the 10 team names exactly as written.
2. get_matchups with week C. If C is more than 1, also get_matchups with week C minus 1.
3. get_standings.
4. get_roster ten times: team_id "1", "2", "3", "4", "5", "6", "7", "8", "9", "10".
5. get_transactions with type "pending_trade".

Then answer with exactly four code blocks and nothing else: no greeting, no notes, no summary.
Rules for every block:
- The first line is the header line shown below, copied exactly.
- Put one TAB character between columns. Never use spaces, commas or | to separate columns.
- Team names: copy them exactly as Flaim writes them, including apostrophes.
- Never guess. Use only what the calls returned.

Block 1, Scores. Header:
week	team_a	cats_a	cats_b	team_b	status
One line per matchup, week C minus 1 first, then week C.
team_a = home teamName. cats_a = home categoryScore wins. cats_b = away categoryScore wins. team_b = away teamName.
status = Final when the matchup status is "final". Otherwise status = In progress.
Leave out a matchup whose status is "upcoming".

Block 2, Standings. Header:
rank	team	w	l	t
One line per team, rank 1 first. w, l, t = that team's total wins, losses and ties. Last line of the block: END

Block 3, Rosters. Header:
team	player	nba_team	pos	slot	status
One line per player, team 1 first, players in the order Flaim returned them. All 10 teams, every player.
team = the fantasy team name. player = name. nba_team = team. pos = position. slot = selectedPosition. status = status, or empty when the player has no status.
Last line of the block: END

Block 4, Trades. Header:
team_a	a_gets	team_b	b_gets	processes
One line per pending trade. team_a = first team name. a_gets = the players team_a acquires, with ", " between names. team_b = second team name. b_gets = the players team_b acquires. processes = Pending vote
If there are no pending trades, write only the header. Last line of the block: END
````

## QUICK prompt

````text
You are the reporter for the UBE League Hub. Use only the Flaim connector. Do not use memory or the web. Do not give advice.

League: platform "yahoo", sport "basketball", league_id "478.l.211732", season_year 2026. The teams have team_id 1 to 10.

Do these calls in this order:
1. get_league_info. Note the 10 team names exactly as written.
2. get_roster ten times: team_id "1", "2", "3", "4", "5", "6", "7", "8", "9", "10".
3. get_transactions with type "pending_trade".

Then answer with exactly two code blocks and nothing else: no greeting, no notes, no summary.
Rules for every block:
- The first line is the header line shown below, copied exactly.
- Put one TAB character between columns. Never use spaces, commas or | to separate columns.
- Team names: copy them exactly as Flaim writes them, including apostrophes.
- Never guess. Use only what the calls returned.

Block 1, Rosters. Header:
team	player	nba_team	pos	slot	status
One line per player, team 1 first, players in the order Flaim returned them. All 10 teams, every player.
team = the fantasy team name. player = name. nba_team = team. pos = position. slot = selectedPosition. status = status, or empty when the player has no status.
Last line of the block: END

Block 2, Trades. Header:
team_a	a_gets	team_b	b_gets	processes
One line per pending trade. team_a = first team name. a_gets = the players team_a acquires, with ", " between names. team_b = second team name. b_gets = the players team_b acquires. processes = Pending vote
If there are no pending trades, write only the header. Last line of the block: END
````

## Good to know

- Flaim shows the pending trades Yahoo lets your account see. If a trade is missing, type it into the Trades tab by hand, above the `END` line.
- Typing by hand is fine in every tab. Team columns have a dropdown with the valid names.
- New season: change the `league_id` and `season_year` in both prompts.
