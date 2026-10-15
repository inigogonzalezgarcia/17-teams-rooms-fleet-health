import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rooms_health import cli, simulate
from rooms_health.model import Room, load_devices, parse_device
from rooms_health.report import append_history, morning_check
from rooms_health.rules import AT_RISK, NOT_READY, READY, Settings, evaluate_fleet

NOW = datetime(2026, 10, 19, 7, 30, tzinfo=timezone.utc)


def raw(**over):
    d = simulate.device(1, "Madrid", "Prado", "crestron", 1, None, NOW)
    for path, value in over.items():
        node = d
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return d


def room(prio=False):
    return {"mad-prado@contoso.example": Room("mad-prado@contoso.example", "Prado", "Madrid", "6", 8, prio)}


def one(device_raw, rooms=None, bookings=(), cfg=None):
    return evaluate_fleet([parse_device(device_raw)], room() if rooms is None else rooms, list(bookings), NOW, cfg)[0]


class Rules(unittest.TestCase):
    def test_healthy_room_is_ready(self):
        r = one(raw())
        self.assertEqual(r.readiness, READY)
        self.assertEqual(r.issues, [])

    def test_offline_hides_sign_in_and_peripheral_noise(self):
        r = one(raw(health__connection__connectionStatus="disconnected",
                    health__loginStatus__teamsConnection__connectionStatus="disconnected"))
        self.assertEqual(r.readiness, NOT_READY)
        self.assertEqual([i.code for i in r.issues], ["offline"])

    def test_required_vs_optional_peripheral(self):
        d = raw()
        d["health"]["peripheralsHealth"]["roomCameraHealth"]["connection"]["connectionStatus"] = "disconnected"
        self.assertEqual(one(d).readiness, NOT_READY)
        d = raw()
        d["health"]["peripheralsHealth"]["contentCameraHealth"]["connection"]["connectionStatus"] = "disconnected"
        self.assertEqual(one(d).readiness, AT_RISK)

    def test_exchange_failure_is_at_risk_not_blocking(self):
        r = one(raw(health__loginStatus__exchangeConnection__connectionStatus="disconnected"))
        self.assertEqual(r.readiness, AT_RISK)

    def test_stale_heartbeat_threshold(self):
        old = (NOW - timedelta(hours=5)).isoformat()
        self.assertEqual(one(raw(health__connection__lastModifiedDateTime=old)).readiness, READY)
        r = one(raw(health__connection__lastModifiedDateTime=old), cfg=Settings(stale_hours=4))
        self.assertEqual(r.issues[0].code, "stale")

    def test_second_display_is_warning_first_is_critical(self):
        d = simulate.device(1, "Madrid", "Prado", "crestron", 2, "display2", NOW)
        self.assertEqual(one(d).readiness, AT_RISK)
        d["health"]["peripheralsHealth"]["displayHealthCollection"][0]["connection"]["connectionStatus"] = "disconnected"
        self.assertEqual(one(d).readiness, NOT_READY)

    def test_firmware_drift_needs_a_baseline_of_three(self):
        devs = [simulate.device(i, "Madrid", f"R{i}", "logitech", 1, None, NOW, upn=f"r{i}@x") for i in range(3)]
        devs.append(simulate.device(9, "Madrid", "Odd", "logitech", 1, "drift", NOW, upn="odd@x"))
        results = evaluate_fleet([parse_device(d) for d in devs], {}, [], NOW)
        odd = next(r for r in results if r.device.room_account == "odd@x")
        self.assertIn("drift", [i.code for i in odd.issues])
        self.assertEqual(odd.readiness, READY)            # info only

    def test_unregistered_room_is_flagged(self):
        r = one(raw(), rooms={})
        self.assertEqual([i.code for i in r.issues], ["unregistered"])

    def test_ordering_puts_priority_and_soonest_first(self):
        devs = [simulate.device(i, "Madrid", n, "crestron", 1, "camera", NOW, upn=f"{n}@x") for i, n in
                enumerate(["late", "soon", "vip"])]
        rooms = {f"{n}@x": Room(f"{n}@x", n, "Madrid", "1", 6, n == "vip") for n in ["late", "soon", "vip"]}
        from rooms_health.model import Booking
        bookings = [Booking("late@x", NOW + timedelta(hours=5), NOW + timedelta(hours=6)),
                    Booking("soon@x", NOW + timedelta(minutes=20), NOW + timedelta(hours=1)),
                    Booking("vip@x", NOW + timedelta(hours=4), NOW + timedelta(hours=5))]
        order = [r.room.name for r in evaluate_fleet([parse_device(d) for d in devs], rooms, bookings, NOW)]
        self.assertEqual(order, ["vip", "soon", "late"])

    def test_missing_sections_do_not_crash(self):
        d = parse_device({"id": "x", "currentUser": {"displayName": "Room"}})
        self.assertEqual(d.connection, "unknown")
        self.assertEqual(evaluate_fleet([d], {}, [], NOW)[0].readiness, READY)


class EndToEnd(unittest.TestCase):
    def test_demo_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cli.main(["demo", "--out", str(tmp / "out"), "--data", str(tmp / "data")])
            html = (tmp / "out" / "report.html").read_text(encoding="utf-8")
            self.assertIn("Needs attention", html)
            self.assertIn("Concorde", html)
            with open(tmp / "out" / "actions.csv", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertTrue(any(r["issue"] == "Device offline" for r in rows))
            check = (tmp / "out" / "morning_check.md").read_text(encoding="utf-8")
            self.assertTrue(check.splitlines()[4].startswith("1. [ ] **Paris · Concorde**"))
            devices = load_devices(tmp / "data" / "teams_rooms_health.json")
            self.assertEqual(len(devices), 25)

    def test_graph_value_wrapper_and_plain_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "d.json"
            p.write_text(json.dumps([raw()]), encoding="utf-8")
            self.assertEqual(len(load_devices(p)), 1)

    def test_history_keeps_one_line_per_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "h.jsonl"
            res = evaluate_fleet([parse_device(raw())], room(), [], NOW)
            append_history(p, NOW, res)
            rows = append_history(p, NOW, res)
            self.assertEqual(len(rows), 1)

    def test_morning_check_when_all_ready(self):
        res = evaluate_fleet([parse_device(raw())], room(), [], NOW)
        self.assertIn("All rooms ready", morning_check(res, NOW, 3))


if __name__ == "__main__":
    unittest.main()
