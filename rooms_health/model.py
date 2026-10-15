"""Load the three inputs: device health (JSON), the room register (CSV) and, optionally, bookings (CSV).

The device JSON follows the shape of the Microsoft Graph `teamworkDevice` resource with its
`health` object merged in (see scripts/Export-TeamsRoomsHealth.ps1). Parsing is tolerant:
missing sections become "unknown" instead of failing the whole report.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Peripheral keys in teamworkPeripheralsHealth, with a readable name and whether a room
# cannot hold a normal meeting without it.
PERIPHERALS = {
    "roomCameraHealth": ("Room camera", True),
    "microphoneHealth": ("Microphone", True),
    "speakerHealth": ("Speaker", True),
    "communicationSpeakerHealth": ("Communication speaker", False),
    "contentCameraHealth": ("Content camera", False),
}

SOFTWARE = {
    "teamsClientSoftwareUpdateStatus": "Teams Rooms app",
    "operatingSystemSoftwareUpdateStatus": "Operating system",
    "firmwareSoftwareUpdateStatus": "Firmware",
    "partnerAgentSoftwareUpdateStatus": "Partner agent",
    "adminAgentSoftwareUpdateStatus": "Admin agent",
    "companyPortalSoftwareUpdateStatus": "Company Portal",
}


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _status(node: dict | None) -> str:
    """connectionStatus of a nested `{"connection": {...}}` or `{"connectionStatus": ...}` node."""
    if not isinstance(node, dict):
        return "unknown"
    if "connection" in node and isinstance(node["connection"], dict):
        node = node["connection"]
    return str(node.get("connectionStatus") or "unknown")


@dataclass
class Peripheral:
    key: str
    name: str
    status: str            # connected / disconnected / unknown
    required: bool


@dataclass
class Software:
    name: str
    freshness: str         # latest / outdated / unknown
    current: str
    available: str


@dataclass
class Device:
    id: str
    room_account: str
    device_type: str
    manufacturer: str
    model: str
    serial: str
    health_status: str     # Graph healthStatus: healthy / nonUrgent / degraded / critical / offline / unknown
    connection: str
    last_seen: datetime | None
    teams_signin: str
    exchange_signin: str
    peripherals: list[Peripheral] = field(default_factory=list)
    displays: list[str] = field(default_factory=list)   # one status per display
    hdmi_ingest: str = "unknown"
    compute: str = "unknown"
    software: list[Software] = field(default_factory=list)

    def version(self, name: str) -> str:
        for s in self.software:
            if s.name == name:
                return s.current
        return ""


def parse_device(raw: dict) -> Device:
    health = raw.get("health") or {}
    hw = raw.get("hardwareDetail") or {}
    user = raw.get("currentUser") or {}
    conn = health.get("connection") or {}
    login = health.get("loginStatus") or {}
    per = health.get("peripheralsHealth") or {}
    sw = health.get("softwareUpdateHealth") or {}
    hwh = health.get("hardwareHealth") or {}

    peripherals = []
    for key, (name, required) in PERIPHERALS.items():
        node = per.get(key)
        if node is None:
            continue
        optional = bool(node.get("isOptional", not required))
        peripherals.append(Peripheral(key, name, _status(node), required and not optional))

    software = []
    for key, name in SOFTWARE.items():
        node = sw.get(key)
        if not isinstance(node, dict):
            continue
        software.append(Software(name, str(node.get("softwareFreshness") or "unknown"),
                                 str(node.get("currentVersion") or ""), str(node.get("availableVersion") or "")))

    return Device(
        id=str(raw.get("id", "")),
        room_account=str(user.get("userPrincipalName") or user.get("displayName") or raw.get("id", "")).lower(),
        device_type=str(raw.get("deviceType") or "unknown"),
        manufacturer=str(hw.get("manufacturer") or ""),
        model=str(hw.get("model") or ""),
        serial=str(hw.get("serialNumber") or ""),
        health_status=str(raw.get("healthStatus") or "unknown"),
        connection=str(conn.get("connectionStatus") or "unknown"),
        last_seen=parse_ts(conn.get("lastModifiedDateTime") or raw.get("lastModifiedDateTime")),
        teams_signin=_status(login.get("teamsConnection")),
        exchange_signin=_status(login.get("exchangeConnection")),
        peripherals=peripherals,
        displays=[_status(d) for d in per.get("displayHealthCollection") or []],
        hdmi_ingest=_status(hwh.get("hdmiIngestHealth")),
        compute=_status(hwh.get("computeHealth")),
        software=software,
    )


def load_devices(path: Path) -> list[Device]:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("value", [])
    return [parse_device(d) for d in data]


@dataclass
class Room:
    account: str
    name: str
    site: str
    floor: str
    capacity: int
    priority: bool         # boardroom, executive floor, client-facing


def load_rooms(path: Path | None) -> dict[str, Room]:
    if not path:
        return {}
    rooms = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            acc = row["room_account"].strip().lower()
            rooms[acc] = Room(acc, row.get("name", acc).strip(), row.get("site", "").strip(), row.get("floor", "").strip(),
                              int(row.get("capacity") or 0),
                              row.get("priority", "").strip().lower() in {"yes", "true", "1", "vip", "high"})
    return rooms


@dataclass
class Booking:
    account: str
    start: datetime
    end: datetime


def load_bookings(path: Path | None) -> list[Booking]:
    if not path:
        return []
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            start, end = parse_ts(row["start"]), parse_ts(row["end"])
            if start and end:
                out.append(Booking(row["room_account"].strip().lower(), start, end))
    return out
