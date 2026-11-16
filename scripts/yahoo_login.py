#!/usr/bin/env python3
"""One-time Yahoo login. Takes the code from the https://localhost:8080/?code=... address and saves the refresh key.
The key is written to the file named by NEW_REFRESH_TOKEN_FILE; the workflow stores it as a secret. Nothing is printed."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hub import yahoo  # noqa: E402


def main():
    raw = os.environ.get("YAHOO_CODE", "").strip()
    m = re.search(r"[?&]code=([^&#\s]+)", raw)
    code = m.group(1) if m else raw
    if not code:
        print("No code given. Paste the code from the localhost address.")
        return 1
    yahoo.mask(code)
    try:
        out = yahoo.exchange_code(code)
    except RuntimeError:
        print("Yahoo did not accept the code. Codes expire within minutes and work once: open the Yahoo link again and paste the new code.")
        return 1
    token = out.get("refresh_token")
    target = os.environ.get("NEW_REFRESH_TOKEN_FILE")
    if not token or not target:
        print("Yahoo did not return a refresh key.")
        return 1
    with open(target, "w", encoding="utf-8") as f:
        f.write(token)
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
