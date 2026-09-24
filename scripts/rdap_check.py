#!/usr/bin/env python3
"""Daily ICANN registration check for names we still want.

Uses the registry RDAP server (the lookup ICANN points to).
A webhook cannot see a stranger register a name. This asks the registry.
"""
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOLDINGS = ROOT / "holdings.json"
STATUS = ROOT / "status.json"
RDAP = "https://rdap.identitydigital.services/rdap/domain/"
PAUSE = 1.5


def load(path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text())


def open_names(holdings):
    names = []
    peak = holdings.get("peak") or {}
    if peak.get("role") == "open":
        names.append(peak["domain"])
    for zone in holdings.get("zones") or []:
        if zone.get("role") == "open":
            names.append(zone["domain"])
    for state in holdings.get("states") or []:
        if state.get("role") == "open":
            names.append(state["domain"])
        if state.get("capitalRole") == "open" and state.get("capitalDomain"):
            names.append(state["capitalDomain"])
    for extra in holdings.get("watch") or []:
        if extra.get("role") == "open":
            names.append(extra["domain"])
    # keep order, drop dupes
    seen = set()
    out = []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def lookup(domain):
    req = urllib.request.Request(
        RDAP + domain,
        headers={"Accept": "application/rdap+json", "User-Agent": "mycountry-registration-check"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            resp.read(200)
            return "registered", resp.status
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return "available", 404
        if err.code == 429:
            return "paused", 429
        return "error", err.code
    except Exception:
        return "error", 0


def main():
    holdings = load(HOLDINGS, {})
    previous = load(STATUS, {"domains": {}})
    prev_domains = previous.get("domains") or {}
    results = {}
    paused = False
    for domain in open_names(holdings):
        if paused:
            old = prev_domains.get(domain) or {}
            results[domain] = {
                "state": old.get("state") or "unchecked",
                "code": old.get("code"),
                "note": "not checked this run",
            }
            continue
        state, code = lookup(domain)
        if state == "paused":
            paused = True
            old = prev_domains.get(domain) or {}
            results[domain] = {
                "state": old.get("state") or "unchecked",
                "code": 429,
                "note": "registry asked us to slow down",
            }
        else:
            results[domain] = {"state": state, "code": code}
        time.sleep(PAUSE)

    newly = []
    for domain, info in results.items():
        was = (prev_domains.get(domain) or {}).get("state")
        if info["state"] == "registered" and was != "registered":
            newly.append(domain)

    payload = {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lookup": "ICANN RDAP at rdap.identitydigital.services",
        "paused": paused,
        "domains": results,
        "newly_registered": newly,
    }
    STATUS.write_text(json.dumps(payload, indent=2) + "\n")
    alert = ROOT / "newly_registered.txt"
    if newly:
        alert.write_text("\n".join(newly) + "\n")
    elif alert.exists():
        alert.unlink()
    print(json.dumps({"checked": len(results), "newly_registered": newly, "paused": paused}))


if __name__ == "__main__":
    main()
