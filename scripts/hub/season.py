"""Season end: keep a final copy under archive/<season>/ and clear the live data."""
import json
import os
import shutil

from . import util

SITE_FILES = ["index.html", "page.html", "shim.js", "shim.css"]


def label(cfg):
    y = int(cfg["season"])
    return "%d-%02d" % (y, (y + 1) % 100)


def archive(cfg):
    name = label(cfg)
    dest = os.path.join(util.ROOT, "archive", name)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(os.path.join(dest, "config"))
    for f in SITE_FILES:
        shutil.copy2(os.path.join(util.ROOT, f), os.path.join(dest, f))
    shutil.copytree(util.DATA, os.path.join(dest, "data"))
    state_file = os.path.join(dest, "data", "state.json")
    state = util.read("state", {}) or {}
    with open(state_file, "w", encoding="utf-8") as f:
        f.write(util.dump({**state, "season": name, "season_over": False}))
    with open(os.path.join(dest, "config", "site.json"), "w", encoding="utf-8") as f:
        f.write(util.dump({"archived": True, "season": name}))
    index = os.path.join(util.ROOT, "archive", "index.json")
    try:
        with open(index, encoding="utf-8") as f:
            seasons = json.load(f)
    except (OSError, ValueError):
        seasons = []
    if name not in seasons:
        seasons.append(name)
    with open(index, "w", encoding="utf-8") as f:
        f.write(json.dumps(seasons) + "\n")
    clear(name)
    return dest


def clear(name):
    for ds in util.PAGE_DATASETS:
        util.write(ds, [])
    for extra in ("teams", "weeks", "htb"):
        if os.path.exists(util.path(extra)):
            util.write(extra, [])
    state = util.read("state", {}) or {}
    util.write("state", {**state, "season": name, "season_over": True})
