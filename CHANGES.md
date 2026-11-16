# What differs from the Claude hub

`page.html` is a copy of the Claude hub's page (store document `files/index.html`, version 39, read Nov 16 2026).
All ranking, playoff, matchup, slate and trade-analyzer code is untouched. `scripts/rank.js` runs that same code
for the team cards, so the page and the update script cannot disagree.

## Text changed in page.html (2 lines, Settings tab, "Update schedule" card)

| Claude hub | This version |
|---|---|
| Daily: injuries, news, pending trades. | Daily at 2:30 PM (Manila), automatic: Yahoo scores, standings, rosters, IL slots and pending trades; injuries; news. |
| Yahoo sync (rosters, IL slots, standings, scores) on request. | Updates run on their own. No manual sync needed. |

## Team names shown on this hub (1 line in page.html)

`config/display_names.json` sets the name shown for a team, whatever it is called on Yahoo:
team 1 shows as **Team Hali** (Yahoo: The Haliban) and team 4 as **Team Luka** (Yahoo: Master Luka’s Cotton Pickers).
`page.html` marks your own team by name, so that line reads `mine: "Team Hali",` instead of `mine: "The Haliban",`.
If you change team 1's display name, change that line to match.

Check it yourself: compare `page.html` with the Claude hub's page; only these three lines differ.

## Added around the page (not inside it)

- `shim.js` and `shim.css`: stand in for the Claude dashboard (data loading, colors, sizes, light and dark mode).
- Fonts: Inter and Source Serif 4 replace Anthropic Sans and Anthropic Serif, which are not free to host.
- News table: the "Fantasy angle" column is hidden while every headline has no angle (headlines only).
- Trade market: saved in a Google Sheet. Saving asks for the passcode once per browser.
- Footer: "Updated <time>" and links to past seasons. Banner when a season is over or when viewing an archive.

## Data differences

- News: ESPN headlines with links, no fantasy-angle text.
- Injury detail: body part only (for example "Left hamstring"), from ESPN.
- NBA schedule: the whole regular season is loaded, so Matchup and Weekly Slate can show any week.
- Changelog rows are written by the script (for example "Week 5 live scores; injuries; news.").
