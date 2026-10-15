"""Fictional demo fleet: 24 rooms in three offices of a made-up company (contoso.example).

Nothing here comes from a real tenant. Faults are placed on purpose so every rule fires at least once.
"""
from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEMO_NOW = datetime(2026, 10, 19, 7, 30, tzinfo=timezone.utc)   # a Monday, before the first meetings

MODELS = {
    "crestron": ("Crestron", "Flex UC-B160-T", "teamsRoom",
                 {"Teams Rooms app": "5.2.115.0", "Operating system": "10.0.22631", "Firmware": "1.4.2"}),
    "logitech": ("Logitech", "Tap + Rally Bar", "teamsRoom",
                 {"Teams Rooms app": "5.2.115.0", "Operating system": "10.0.22631", "Firmware": "1.12.4"}),
    "poly": ("Poly", "Studio X50", "collaborationBar",
             {"Teams Rooms app": "1449/1.0.96.2024", "Operating system": "4.1.0", "Firmware": "4.1.0-418"}),
}
SW_KEYS = {"Teams Rooms app": "teamsClientSoftwareUpdateStatus", "Operating system": "operatingSystemSoftwareUpdateStatus",
           "Firmware": "firmwareSoftwareUpdateStatus"}

# (site, floor, name, capacity, priority, model, displays)
ROOMS = [
    ("Madrid", "7", "Boardroom", 18, True, "crestron", 2), ("Madrid", "7", "Retiro", 10, True, "crestron", 2),
    ("Madrid", "6", "Prado", 8, False, "crestron", 1), ("Madrid", "6", "Atocha", 8, False, "logitech", 1),
    ("Madrid", "5", "Lavapies", 6, False, "logitech", 1), ("Madrid", "5", "Chamberi", 6, False, "logitech", 1),
    ("Madrid", "4", "Malasana", 4, False, "poly", 1), ("Madrid", "4", "Salamanca", 4, False, "poly", 1),
    ("Madrid", "3", "Arganzuela", 12, False, "crestron", 2), ("Madrid", "3", "Tetuan", 6, False, "logitech", 1),
    ("Paris", "5", "Concorde", 16, True, "crestron", 2), ("Paris", "5", "Opera", 8, False, "crestron", 1),
    ("Paris", "4", "Marais", 6, False, "logitech", 1), ("Paris", "4", "Bastille", 6, False, "logitech", 1),
    ("Paris", "3", "Montmartre", 4, False, "poly", 1), ("Paris", "3", "Belleville", 4, False, "poly", 1),
    ("Paris", "2", "Pigalle", 10, False, "crestron", 2),
    ("Lisbon", "2", "Alfama", 10, True, "crestron", 2), ("Lisbon", "2", "Chiado", 6, False, "logitech", 1),
    ("Lisbon", "1", "Belem", 6, False, "logitech", 1), ("Lisbon", "1", "Graca", 4, False, "poly", 1),
    ("Lisbon", "1", "Baixa", 4, False, "poly", 1), ("Lisbon", "1", "Estrela", 8, False, "crestron", 1),
    ("Lisbon", "1", "Alcantara", 6, False, "logitech", 1),
]
CODE = {"Madrid": "mad", "Paris": "par", "Lisbon": "lis"}

# Faults placed on purpose: room name -> what is wrong
FAULTS = {
    "Boardroom": "exchange_signin",       # resource account password expired, meeting at 08:30
    "Prado": "camera",
    "Opera": "offline",
    "Concorde": "teams_signin",           # blocked by a new Conditional Access policy
    "Pigalle": "display2",
    "Bastille": "hdmi",
    "Chiado": "teams_outdated",
    "Belem": "teams_outdated",
    "Baixa": "stale",
    "Tetuan": "drift",
    "Estrela": "microphone",
}
UNREGISTERED = "mad-room-lab@contoso.example"   # a device that was set up but never added to the register


def account(site: str, name: str) -> str:
    return f"{CODE[site]}-{name.lower()}@contoso.example"


def _conn(status: str, ts: str) -> dict:
    return {"connectionStatus": status, "lastModifiedDateTime": ts}


def device(i: int, site: str, name: str, model_key: str, displays: int, fault: str | None, now: datetime,
           upn: str | None = None) -> dict:
    manufacturer, model, dtype, versions = MODELS[model_key]
    seen = now - timedelta(minutes=3 + i)
    if fault == "stale":
        seen = now - timedelta(hours=9, minutes=10)
    if fault == "offline":
        seen = now - timedelta(hours=14)
    ts = seen.isoformat().replace("+00:00", "Z")
    connected = "disconnected" if fault == "offline" else "connected"

    def per(status="connected", optional=False):
        return {"connection": _conn(status, ts), "isOptional": optional}

    software = {}
    for label, key in SW_KEYS.items():
        current = versions[label]
        fresh = "latest"
        available = current
        if label == "Teams Rooms app" and fault == "teams_outdated":
            current, fresh = "5.1.33.0", "outdated"
        if label == "Firmware" and fault == "drift":
            current = "1.11.9"
        software[key] = {"softwareFreshness": fresh, "currentVersion": current, "availableVersion": available}
    software["adminAgentSoftwareUpdateStatus"] = {"softwareFreshness": "latest", "currentVersion": "1.0.0.202409",
                                                  "availableVersion": "1.0.0.202409"}

    health = {
        "connection": _conn(connected, ts),
        "loginStatus": {
            "teamsConnection": _conn("disconnected" if fault == "teams_signin" else connected, ts),
            "exchangeConnection": _conn("disconnected" if fault == "exchange_signin" else connected, ts),
        },
        "peripheralsHealth": {
            "roomCameraHealth": per("disconnected" if fault == "camera" else "connected"),
            "microphoneHealth": per("disconnected" if fault == "microphone" else "connected"),
            "speakerHealth": per(),
            "contentCameraHealth": per(optional=True) if model_key == "crestron" else None,
            "displayHealthCollection": [
                {"connection": _conn("disconnected" if (fault == "display2" and n == 2) else "connected", ts)}
                for n in range(1, displays + 1)],
        },
        "hardwareHealth": {
            "computeHealth": {"connection": _conn("connected", ts)},
            "hdmiIngestHealth": {"connection": _conn("disconnected" if fault == "hdmi" else "connected", ts)},
        },
        "softwareUpdateHealth": software,
    }
    health["peripheralsHealth"] = {k: v for k, v in health["peripheralsHealth"].items() if v is not None}
    status = {"offline": "offline", "teams_signin": "critical", "camera": "critical", "microphone": "critical",
              "exchange_signin": "degraded", "display2": "degraded", "hdmi": "nonUrgent",
              "teams_outdated": "nonUrgent"}.get(fault or "", "healthy")
    upn = upn or account(site, name)
    return {
        "id": f"00000000-0000-4000-8000-{i:012d}",
        "deviceType": dtype,
        "healthStatus": status,
        "activityState": "idle" if connected == "connected" else "unknown",
        "hardwareDetail": {"manufacturer": manufacturer, "model": model, "serialNumber": f"DEMO{i:05d}"},
        "currentUser": {"displayName": f"{site} {name}", "userPrincipalName": upn},
        "lastModifiedDateTime": ts,
        "health": health,
    }


def bookings(now: datetime, rng: random.Random) -> list[dict]:
    rows = []
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for site, _floor, name, _cap, priority, _m, _d in ROOMS:
        acc = account(site, name)
        slots = [h for h in range(8, 18) if rng.random() < (0.6 if priority else 0.4)]
        if name == "Boardroom":
            slots = sorted(set(slots) | {8})
        for h in slots:
            start = day + timedelta(hours=h, minutes=30 if name == "Boardroom" and h == 8 else 0)
            rows.append({"room_account": acc, "start": start.isoformat().replace("+00:00", "Z"),
                         "end": (start + timedelta(minutes=45)).isoformat().replace("+00:00", "Z")})
    return rows


def history(now: datetime, rng: random.Random, days: int = 13) -> list[dict]:
    out = []
    for n in range(days, 0, -1):
        ready = 24 - rng.choice([2, 3, 3, 4, 5, 2, 3])
        out.append({"date": (now - timedelta(days=n)).date().isoformat(), "rooms": 24, "ready": ready,
                    "ready_pct": round(100 * ready / 24, 1)})
    return out


def write_demo(folder: Path, now: datetime = DEMO_NOW, seed: int = 17) -> dict[str, Path]:
    rng = random.Random(seed)
    folder.mkdir(parents=True, exist_ok=True)
    devs = [device(i, site, name, m, disp, FAULTS.get(name), now)
            for i, (site, _f, name, _c, _p, m, disp) in enumerate(ROOMS, 1)]
    devs.append(device(len(ROOMS) + 1, "Madrid", "Lab", "logitech", 1, None, now, upn=UNREGISTERED))
    paths = {"devices": folder / "teams_rooms_health.json", "rooms": folder / "rooms.csv",
             "bookings": folder / "bookings.csv", "history": folder / "history.jsonl"}
    paths["devices"].write_text(json.dumps({"value": devs}, indent=2), encoding="utf-8")
    with open(paths["rooms"], "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["room_account", "name", "site", "floor", "capacity", "priority"])
        for site, floor, name, cap, prio, _m, _d in ROOMS:
            w.writerow([account(site, name), f"{site} · {name}", site, floor, cap, "yes" if prio else "no"])
    with open(paths["bookings"], "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["room_account", "start", "end"])
        w.writeheader()
        w.writerows(bookings(now, rng))
    paths["history"].write_text("".join(json.dumps(h) + "\n" for h in history(now, rng)), encoding="utf-8")
    return paths
