#!/usr/bin/env python3
"""
Minecraft (Java Edition) username sniper.

Modes
  watch : poll until the name becomes available, then claim it instantly.
  timed : wait until a known drop time (UTC), then fire a burst of claim requests.

Setup
  pip install requests
  export MC_TOKEN="<your Minecraft services access token>"   # Windows: set MC_TOKEN=...

Usage
  python mc_sniper.py Notch2                         # watch mode, polls every 20s
  python mc_sniper.py Notch2 --interval 30
  python mc_sniper.py Notch2 --at 2026-11-08T14:30:00 --burst 5 --delay-ms 80

Notes
  * The token belongs to YOUR account and expires after roughly a day.
  * Name changes are limited to once per 30 days, so you only get one good shot.
  * Don't hammer the API: aggressive polling gets you rate limited (HTTP 429).
"""
import argparse
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone

import requests

API = "https://api.minecraftservices.com/minecraft/profile/name"
NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")

done = threading.Event()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def check_available(session, name, token):
    """True / False, or None if rate limited."""
    r = session.get(f"{API}/{name}/available", headers=auth(token), timeout=10)
    if r.status_code == 401:
        sys.exit("Token rejected (401). It has probably expired; get a fresh one.")
    if r.status_code == 429:
        return None
    r.raise_for_status()
    return r.json().get("status") == "AVAILABLE"


def claim(session, name, token):
    """Attempt the name change. Returns True on success."""
    if done.is_set():
        return False
    try:
        r = session.put(f"{API}/{name}", headers=auth(token), timeout=10)
    except requests.RequestException as e:
        print(f"[{stamp()}] request error: {e}")
        return False
    print(f"[{stamp()}] claim -> HTTP {r.status_code} {r.text[:120]}")
    if r.status_code == 200:
        done.set()
        return True
    if r.status_code == 401:
        done.set()
        print("Token rejected (401).")
    return False


def stamp():
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def watch(name, token, interval):
    session = requests.Session()
    print(f"Watching '{name}' every {interval}s. Ctrl+C to stop.")
    backoff = interval
    while True:
        try:
            avail = check_available(session, name, token)
        except requests.RequestException as e:
            print(f"[{stamp()}] network error: {e}")
            time.sleep(interval)
            continue

        if avail is None:
            backoff = min(backoff * 2, 300)
            print(f"[{stamp()}] rate limited, backing off {backoff}s")
            time.sleep(backoff)
            continue

        backoff = interval
        if avail:
            print(f"[{stamp()}] '{name}' is AVAILABLE, claiming...")
            if claim(session, name, token):
                print(f"Success! You now own '{name}'.")
                return
            print("Claim failed; resuming watch.")
        else:
            print(f"[{stamp()}] '{name}' not available yet")
        time.sleep(interval)


def timed(name, token, drop_time, burst, delay_ms, lead):
    session = requests.Session()
    target = drop_time.timestamp() - lead
    wait = target - time.time()
    if wait > 0:
        print(f"Waiting {wait:.1f}s until {lead}s before the drop...")
        while time.time() < target - 1:
            time.sleep(0.5)
        while time.time() < target:  # tight spin for the last second
            pass
    print(f"[{stamp()}] firing {burst} requests, {delay_ms}ms apart")
    threads = []
    for _ in range(burst):
        t = threading.Thread(target=claim, args=(session, name, token))
        t.start()
        threads.append(t)
        time.sleep(delay_ms / 1000)
    for t in threads:
        t.join()
    print("Success! Name claimed." if done.is_set() else "No successful claim this round.")


def main():
    p = argparse.ArgumentParser(description="Minecraft username sniper")
    p.add_argument("name")
    p.add_argument("--at", help="drop time in UTC, e.g. 2026-11-08T14:30:00 (enables timed mode)")
    p.add_argument("--interval", type=float, default=20, help="watch mode poll seconds (default 20)")
    p.add_argument("--burst", type=int, default=5, help="timed mode: number of claim requests")
    p.add_argument("--delay-ms", type=float, default=80, help="timed mode: gap between requests")
    p.add_argument("--lead", type=float, default=0.2, help="timed mode: start this many seconds early")
    a = p.parse_args()

    if not NAME_RE.match(a.name):
        sys.exit("Names must be 3-16 characters: letters, digits, underscore.")
    token = os.environ.get("MC_TOKEN")
    if not token:
        sys.exit("Set the MC_TOKEN environment variable first.")

    try:
        if a.at:
            drop = datetime.fromisoformat(a.at).replace(tzinfo=timezone.utc)
            timed(a.name, token, drop, a.burst, a.delay_ms, a.lead)
        else:
            watch(a.name, token, max(a.interval, 5))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
