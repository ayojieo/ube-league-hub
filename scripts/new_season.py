#!/usr/bin/env python3
"""Start a new season. Edit config/league.json first (league_key, season, dates), then run the New season workflow.
Rebuilds teams, schedule, standings and rosters from Yahoo, keeps each manager's tagline, and starts a fresh changelog."""
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hub import build, season, sources, util, yahoo  # noqa: E402

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

    y = yahoo.Client(cfg)
    meta = y.meta()
    y_teams = y.rosters()
    teams, _ = build.team_names([], y_teams, cfg)
    names = {t["team_id"]: t["team"] for t in teams}
    managers = {t["team_id"]: t["manager"] for t in teams}
    problems = []
    try:
        weeks = y.game_weeks()
    except Exception:
        weeks = []
    schedule = []
    for w in range(1, cfg["regular_season_last_week"] + 1):
        try:
            schedule = build.apply_scoreboard(schedule, w, y.scoreboard(w), names, cfg, meta["current_week"])
        except Exception as e:
            problems.append("Week %d schedule: %s" % (w, e))
    standings = build.standings_rows(y.standings(), names, managers)
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
    try:
        need = build.players_needing_yahoo_stats(y_teams, [], htb, alias)
        y_stats = y.season_stats(need) if need else {}
    except Exception as e:
        y_stats = {}
        problems.append("Yahoo stats: %s" % e)
    rosters, players, injuries, _ = build.build_rosters(y_teams, names, [], espn, htb, y_stats, today, name, alias)
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
    util.write("state", {"season": name, "season_over": False, "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    if y.new_refresh and os.environ.get("NEW_REFRESH_TOKEN_FILE"):
        with open(os.environ["NEW_REFRESH_TOKEN_FILE"], "w", encoding="utf-8") as f:
            f.write(y.new_refresh)
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
        print("Check league_key in config/league.json and that the Yahoo login is still valid.")
        sys.exit(1)
