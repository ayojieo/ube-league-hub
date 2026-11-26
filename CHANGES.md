# What differs from the Claude hub

`page.html` is a copy of the Claude hub's page (store document `files/index.html`, version 56, read Nov 27 2026).
All ranking, playoff, matchup, slate and trade-analyzer code is untouched. `scripts/rank.js` runs that same code
for the team cards, so the page and the update script cannot disagree.

Since the previous copy (version 39) the Claude hub added: team cards with a nickname, green and red pills
(no "Punt" label) and Core / Swing / Underdog rows; the Cats/wk and Healthy columns in the Category ranks table;
and Settings lines explaining them. They come along unchanged.

## Text changed in page.html (3 lines, Settings tab)

| Claude hub | This version |
|---|---|
| Rosters, standings and scores: Yahoo. NBA games: … | Rosters, standings and scores: Yahoo, pasted into the Google Sheet. NBA games: … |
| Daily: injuries, news, pending trades. | Daily at 2:30 PM (Manila), automatic: league data from the Google Sheet (scores, standings, rosters, IL slots, pending trades); injuries; news. |
| Yahoo sync (rosters, IL slots, standings, scores) on request. | League data is pasted into the Google Sheet each week (and after trades or adds/drops). Everything else runs on its own. |

## Team names shown on this hub (1 line in page.html)

`config/display_names.json` sets the name shown for a team, whatever it is called on Yahoo:
team 1 shows as **Team Hali** (Yahoo: The Haliban) and team 4 as **Team Luka** (Yahoo: Master Luka’s Cotton Pickers).
`page.html` marks your own team by name, so that line reads `mine: "Team Hali",` instead of `mine: "The Haliban",`.
If you change team 1's display name, change that line to match.

Check it yourself: compare `page.html` with the Claude hub's page; only these four lines differ.

## Added around the page (not inside it)

- `shim.js` and `shim.css`: stand in for the Claude dashboard (data loading, colors, sizes, light and dark mode).
- Fonts: Inter and Source Serif 4 replace Anthropic Sans and Anthropic Serif, which are not free to host.
- News table: the "Fantasy angle" column is hidden while every headline has no angle (headlines only).
- Trade market: saved in the Google Sheet. Saving asks for the passcode once per browser.
- Footer: "Updated <time>", "League data: Google Sheet · pasted <date>" (from `data/state.json`) and links to past seasons.
- Banner: when a season is over, when viewing an archive, or "League data last updated <date>." when nothing was pasted for more than 8 days.

## Data differences

- League data (scores, standings, rosters, IL slots, pending trades) comes only from the Google Sheet. There is no waiver order (the last known one is kept) and no Yahoo injury note (ESPN's detail is used, else the last known one). Brand-new players outside Hashtagbasketball's top 200 start with no stats and the minimum value until they are listed.
- Team cards: the update refreshes only the green pill (3–4 strongest categories by current rank) and the red pill (3–4 weakest). Nicknames and descriptions are written by hand and never changed.
- News: ESPN headlines with links, no fantasy-angle text.
- Injury detail: body part only (for example "Left hamstring"), from ESPN.
- NBA schedule: the whole regular season is loaded, so Matchup and Weekly Slate can show any week.
- Changelog rows are written by the script, for example "Week 6 final; standings; 3 roster moves (from Google Sheet); injuries; news."
