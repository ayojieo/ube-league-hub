#!/usr/bin/env python3
"""Start a new season. First: edit config/league.json (season, dates, rivalry weeks, managers) and fill the Google Sheet
for the new league (Info tab team names, Scores with every week's pairings, Rosters). Then run the New season workflow.
Builds teams, schedule, standings and rosters from the sheet, keeps each manager's nickname, and starts a fresh changelog."""
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hub import build, season, sheet, sources, util  # noqa: E402

DATE_LINE = re.compile(r"const s = new Date\(\d{4}, \d{1,2}, \d{1,2} \+ \(w - 2\) \* 7\);")


def patch_page(cfg):
    """The Weekly Slate works out week dates from the Week 2 start date written in the page. Point it at the new season."""
    path = os.path.join(util.ROOT, "page.html")
    with open(path, encoding="utf-8") as f:
        page = f.read()
    d = dt.date.fromisoformat(cfg["week2_start"])
    new = "const s = new Date(%d, %d, %d + (w - 2) * 7);" % (d.year, d.month - 1, d.day)
    if len(DATE_LINE.findall(page)) != 1:
        return "Weekly Slate dates: could not find the Week 2 date in page.html. Update it by hand."
    patched = DATE_LINE.sub(new, page)
    if patched != page:
        with open(path, "w", encoding="utf-8") as f:
            f.write(patched)
    return None


def main():
    cfg = util.load_config()
    today = util.today(cfg)
    name = season.label(cfg)
    state = util.read("state", {}) or {}
    if not state.get("season_over") and os.environ.get("UBE_CONFIRM", "").lower() != "yes":
        print("The current season is still live. Type yes in the confirm box to replace it.")
        return 1
    old_cards = {}
    for folder in sorted(os.listdir(os.path.join(util.ROOT, "archive"))) if os.path.isdir(os.path.join(util.ROOT, "archive")) else []:
        try:
            import json
            with open(os.path.join(util.ROOT, "archive", folder, "data", "managers.json"), encoding="utf-8") as f:
                for m in json.load(f):
                    old_cards[m["manager"]] = m.get("tagline", "")
        except (OSError, ValueError):
            pass
    for m in util.read("managers", []) or []:
        old_cards[m["manager"]] = m.get("tagline", "")

    lg = sheet.League(sheet.fetch(), [], cfg)
    teams, _ = build.team_names([], lg.yahoo_teams(), cfg)
    names = {t["team_id"]: t["team"] for t in teams}
    managers = {t["team_id"]: t["manager"] for t in teams}
    weeks = []
    schedule = lg.scores([], names, util.week_of(today, cfg, weeks))
    table = lg.standings([], names) or [{"team_id": t["team_id"], "name": t["team"], "rank": i, "w": 0, "l": 0, "t": 0}
                                         for i, t in enumerate(teams, 1)]
    standings = build.standings_rows(table, names, managers)
    sheet_teams = lg.rosters([], names, [])
    if not sheet_teams:
        raise RuntimeError("the Rosters tab is empty. Paste the new rosters first.")
    problems = list(lg.problems)
    last = cfg["regular_season_last_week"]
    missing = [w for w in range(1, last + 1) if not any(r["week"] == w for r in schedule)]
    if missing:
        problems.append("No pairings yet for week%s %s. Paste them into the Scores tab (status Not started); the daily update adds them."
                        % ("s" if len(missing) > 1 else "", ", ".join(map(str, missing))))
    alias = build.aliases()
    try:
        htb = sources.hashtag()
        for line in htb.values():
            line["date"] = today.isoformat()
    except Exception as e:
        htb = {}
        problems.append("%s" % e)
    try:
        espn = sources.injuries()
    except Exception as e:
        espn = None
        problems.append("%s" % e)
    rosters, players, injuries, _ = build.build_rosters(sheet_teams, names, [], espn, htb, None, today, name, alias)
    build.apply_cap(players)
    try:
        games = sources.nba_games(cfg, weeks)
    except Exception as e:
        games = []
        problems.append("%s" % e)
    try:
        news = sources.news()
    except Exception as e:
        news = []
        problems.append("%s" % e)

    note = patch_page(cfg)
    if note:
        problems.append(note)
    util.write("teams", teams)
    util.write("weeks", weeks)
    util.write("htb", sorted(htb.values(), key=lambda r: r["htb_rank"]))
    for ds, rows in (("schedule", schedule), ("standings", standings), ("rosters", rosters), ("players", players), ("injuries", injuries),
                     ("nba_games", games), ("news", news), ("trades", [])):
        util.write(ds, rows)
    cards = [{"team": t["team"], "manager": t["manager"], "tagline": old_cards.get(t["manager"], ""), "playbook": "", "punt": "", "summary": "", "overall_rank": i}
             for i, t in enumerate(teams, 1)]
    try:
        cards = build.manager_rows(cards, teams, build.run_model())
    except Exception as e:
        problems.append("Team cards: %s" % e)
    util.write("managers", cards)
    util.write("log", [{"version": "1.0", "date": today.isoformat(), "change": "Season %s started." % name}])
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    util.write("state", {"season": name, "season_over": False, "updated": now, "league_source": "sheet", "league_updated": lg.updated or now})
    lines = ["## New season: %s" % name, "", "%d teams, %d matchups, %d players loaded." % (len(teams), len(schedule), len(players))]
    if problems:
        lines += ["", "**Problems:**"] + ["- " + p for p in problems]
    text = "\n".join(lines) + "\n"
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        print("New season could not start: %s" % e)
        print("Check the Google Sheet (Info, Scores and Rosters tabs) and config/site.json.")
        sys.exit(1)
