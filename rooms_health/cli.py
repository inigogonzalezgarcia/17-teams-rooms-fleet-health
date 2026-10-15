"""Command line: `demo` builds everything from fictional data, `report` runs on your own export."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from . import report, simulate
from .model import load_bookings, load_devices, load_rooms, parse_ts
from .rules import Settings, evaluate_fleet, summary


def run(devices: Path, rooms: Path | None, bookings: Path | None, out: Path, now: datetime, cfg: Settings,
        title: str, history: Path | None) -> dict:
    results = evaluate_fleet(load_devices(devices), load_rooms(rooms), load_bookings(bookings), now, cfg)
    out.mkdir(parents=True, exist_ok=True)
    hist = report.append_history(history, now, results) if history else []
    (out / "report.html").write_text(report.render_html(results, now, title, hist), encoding="utf-8")
    report.write_actions(results, out / "actions.csv")
    (out / "morning_check.md").write_text(report.morning_check(results, now, cfg.window_hours), encoding="utf-8")
    return summary(results)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rooms_health", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="generate a fictional fleet and build the outputs")
    d.add_argument("--out", type=Path, default=Path("output"))
    d.add_argument("--data", type=Path, default=Path("sample_data"))

    r = sub.add_parser("report", help="build the outputs from your own export")
    r.add_argument("devices", type=Path, help="JSON from scripts/Export-TeamsRoomsHealth.ps1")
    r.add_argument("--rooms", type=Path, help="room register CSV (room_account,name,site,floor,capacity,priority)")
    r.add_argument("--bookings", type=Path, help="optional CSV (room_account,start,end) for today's meetings")
    r.add_argument("--history", type=Path, help="JSONL file to keep one summary line per day")
    r.add_argument("--out", type=Path, default=Path("output"))
    r.add_argument("--now", help="ISO timestamp to evaluate at (default: current time)")
    r.add_argument("--stale-hours", type=float, default=6.0, help="heartbeat age that counts as stale (default 6)")
    r.add_argument("--window-hours", type=float, default=3.0, help="how far ahead a meeting counts as 'soon' (default 3)")
    r.add_argument("--title", default="Teams Rooms · fleet health")

    a = p.parse_args(argv)
    if a.cmd == "demo":
        paths = simulate.write_demo(a.data)
        s = run(paths["devices"], paths["rooms"], paths["bookings"], a.out, simulate.DEMO_NOW, Settings(),
                "Teams Rooms · fleet health (demo data)", paths["history"])
    else:
        now = parse_ts(a.now) if a.now else datetime.now(timezone.utc)
        s = run(a.devices, a.rooms, a.bookings, a.out, now, Settings(a.stale_hours, a.window_hours), a.title, a.history)
    print(f"{s['rooms']} rooms: {s['ready']} ready, {s['at_risk']} at risk, {s['not_ready']} not ready "
          f"({s['priority_not_ready']} priority). Outputs in {a.out}/")
    return 0
