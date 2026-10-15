"""Readiness rules. Each room gets a list of issues and one readiness state:

- Not ready: a meeting in this room would probably fail (offline, Teams not signed in,
  a required camera, microphone, speaker or display missing).
- At risk:   the meeting would work but something will hurt (no calendar on the console,
  stale heartbeat, outdated software, optional peripheral down).
- Ready:     nothing found.

Issues are ranked for the on-site engineer: priority rooms and rooms with a meeting soon first.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .model import Booking, Device, Room

CRITICAL, WARNING, INFO = "critical", "warning", "info"
SEVERITY_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}
NOT_READY, AT_RISK, READY = "Not ready", "At risk", "Ready"

# What to do first for each issue code. Kept short: this text goes into the morning check list.
FIRST_STEP = {
    "offline": "Check power and network at the console; restart the compute unit if it is on but not connected.",
    "stale": "Check the device in the Teams admin center; restart if the last heartbeat does not move.",
    "teams_signin": "Check the resource account password, licence and Conditional Access sign-in logs.",
    "exchange_signin": "Check the resource account mailbox and calendar processing; the console will not show the schedule.",
    "peripheral": "Reseat the USB/HDMI cable at both ends and check the peripheral in the device settings.",
    "display": "Check the display power and HDMI input; confirm the display is on the right source.",
    "hdmi_ingest": "Check the table HDMI cable and the ingest box; test content sharing with a laptop.",
    "compute": "Check the compute unit (power, temperature, disk) in the admin center.",
    "outdated": "Schedule the update in the next maintenance window; do not update a priority room on a meeting day.",
    "drift": "Align with the version on the rest of the model before the next firmware wave.",
    "unregistered": "Add the room to rooms.csv (site, floor, priority) so it is checked and reported properly.",
}


@dataclass
class Issue:
    code: str
    severity: str
    text: str

    @property
    def first_step(self) -> str:
        return FIRST_STEP.get(self.code, "")


@dataclass
class RoomResult:
    device: Device
    room: Room
    issues: list[Issue] = field(default_factory=list)
    next_meeting: datetime | None = None
    meetings_today: int = 0

    @property
    def readiness(self) -> str:
        sev = {i.severity for i in self.issues}
        if CRITICAL in sev:
            return NOT_READY
        if WARNING in sev:
            return AT_RISK
        return READY

    def urgency(self, now: datetime, window: timedelta) -> tuple:
        """Sort key: worst readiness, then priority room, then meeting soonest."""
        rank = {NOT_READY: 0, AT_RISK: 1, READY: 2}[self.readiness]
        soon = self.next_meeting is not None and self.next_meeting - now <= window
        next_in = (self.next_meeting - now).total_seconds() if self.next_meeting else float("inf")
        return (rank, not self.room.priority, not soon, next_in, self.room.name)


@dataclass
class Settings:
    stale_hours: float = 6.0
    window_hours: float = 3.0
    flag_outdated: tuple[str, ...] = ("Teams Rooms app", "Operating system", "Firmware")


def baselines(devices: list[Device]) -> dict[tuple[str, str], str]:
    """Most common version per (model, software). Used to spot rooms that drifted from the rest."""
    counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for d in devices:
        for s in d.software:
            if s.current:
                counts[(d.model, s.name)][s.current] += 1
    return {k: c.most_common(1)[0][0] for k, c in counts.items() if sum(c.values()) >= 3}


def evaluate(d: Device, room: Room, now: datetime, cfg: Settings, base: dict, bookings: list[Booking]) -> RoomResult:
    r = RoomResult(d, room)
    add = r.issues.append

    offline = d.connection == "disconnected" or d.health_status == "offline"
    if offline:
        add(Issue("offline", CRITICAL, "Device offline"))
    elif d.last_seen and now - d.last_seen > timedelta(hours=cfg.stale_hours):
        hours = int((now - d.last_seen).total_seconds() // 3600)
        add(Issue("stale", WARNING, f"No heartbeat for {hours} h"))

    if not offline:
        if d.teams_signin == "disconnected":
            add(Issue("teams_signin", CRITICAL, "Teams sign-in failed"))
        if d.exchange_signin == "disconnected":
            add(Issue("exchange_signin", WARNING, "Exchange sign-in failed (no calendar on the console)"))
        for p in d.peripherals:
            if p.status == "disconnected":
                add(Issue("peripheral", CRITICAL if p.required else WARNING, f"{p.name} disconnected"))
        for i, status in enumerate(d.displays, 1):
            if status == "disconnected":
                label = "Front-of-room display" + (f" {i}" if len(d.displays) > 1 else "")
                add(Issue("display", CRITICAL if i == 1 else WARNING, f"{label} disconnected"))
        if d.hdmi_ingest == "disconnected":
            add(Issue("hdmi_ingest", WARNING, "HDMI ingest disconnected (no wired content sharing)"))
        if d.compute == "disconnected":
            add(Issue("compute", CRITICAL, "Compute unit unhealthy"))

    for s in d.software:
        if s.name in cfg.flag_outdated and s.freshness == "outdated":
            target = f" → {s.available}" if s.available else ""
            add(Issue("outdated", WARNING, f"{s.name} outdated ({s.current}{target})"))
        elif s.freshness != "outdated" and s.current:
            expected = base.get((d.model, s.name))
            if expected and s.current != expected and s.name == "Firmware":
                add(Issue("drift", INFO, f"Firmware {s.current}, rest of the {d.model} fleet on {expected}"))

    if not room.site:
        add(Issue("unregistered", INFO, "Not in the room register"))

    today = [b for b in bookings if b.account == d.room_account and b.start.date() == now.date() and b.end > now]
    r.meetings_today = len(today)
    upcoming = sorted(b.start for b in today)
    r.next_meeting = upcoming[0] if upcoming else None
    r.issues.sort(key=lambda i: SEVERITY_ORDER[i.severity])
    return r


def evaluate_fleet(devices: list[Device], rooms: dict[str, Room], bookings: list[Booking],
                   now: datetime, cfg: Settings | None = None) -> list[RoomResult]:
    cfg = cfg or Settings()
    base = baselines(devices)
    results = []
    for d in devices:
        room = rooms.get(d.room_account) or Room(d.room_account, d.room_account.split("@")[0], "", "", 0, False)
        results.append(evaluate(d, room, now, cfg, base, bookings))
    window = timedelta(hours=cfg.window_hours)
    results.sort(key=lambda r: r.urgency(now, window))
    return results


def summary(results: list[RoomResult]) -> dict:
    total = len(results)
    states = Counter(r.readiness for r in results)
    return {
        "rooms": total,
        "ready": states[READY],
        "at_risk": states[AT_RISK],
        "not_ready": states[NOT_READY],
        "ready_pct": round(100 * states[READY] / total, 1) if total else 0.0,
        "priority_not_ready": sum(1 for r in results if r.room.priority and r.readiness == NOT_READY),
    }
