"""Outputs: a self-contained HTML report, an action list (CSV), a morning check (Markdown) and a history line."""
from __future__ import annotations

import csv
import html
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .rules import AT_RISK, NOT_READY, READY, RoomResult, summary

STATE_CLASS = {NOT_READY: "bad", AT_RISK: "warn", READY: "ok"}
e = html.escape


def _hm(ts: datetime | None) -> str:
    return ts.strftime("%H:%M") if ts else "—"


def write_actions(results: list[RoomResult], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["room", "site", "floor", "priority", "readiness", "severity", "issue", "first_step",
                    "next_meeting_utc", "device_model", "serial", "room_account"])
        for r in results:
            for i in r.issues:
                w.writerow([r.room.name, r.room.site, r.room.floor, "yes" if r.room.priority else "no", r.readiness,
                            i.severity, i.text, i.first_step, _hm(r.next_meeting), r.device.model, r.device.serial,
                            r.device.room_account])


def morning_check(results: list[RoomResult], now: datetime, window_h: float) -> str:
    """Plain list for the engineer doing the walk-round before the first meetings."""
    s = summary(results)
    window = timedelta(hours=window_h)
    lines = [f"# Morning check · {now:%A %d %B %Y, %H:%M} UTC", "",
             f"{s['rooms']} rooms · {s['ready']} ready · {s['at_risk']} at risk · {s['not_ready']} not ready", ""]
    todo = [r for r in results if r.readiness != READY]
    if not todo:
        lines.append("Nothing to check. All rooms ready.")
    for n, r in enumerate(todo, 1):
        flags = []
        if r.room.priority:
            flags.append("PRIORITY ROOM")
        if r.next_meeting and r.next_meeting - now <= window:
            mins = int((r.next_meeting - now).total_seconds() // 60)
            flags.append(f"meeting in {mins // 60} h {mins % 60:02d} min" if mins >= 60 else f"meeting in {mins} min")
        head = f"{n}. [ ] **{r.room.name}** ({r.readiness})"
        lines.append(head + (" · " + " · ".join(flags) if flags else ""))
        where = " · ".join(x for x in (r.room.site, f"floor {r.room.floor}" if r.room.floor else "",
                                         r.device.model) if x)
        lines.append(f"   - {where}")
        for i in r.issues:
            if i.severity == "info":
                continue
            lines.append(f"   - {i.text}. {i.first_step}")
        lines.append("")
    lines.append("Rooms marked READY were not checked by this list. Spot-check one per floor if time allows.")
    return "\n".join(lines) + "\n"


def append_history(path: Path, now: datetime, results: list[RoomResult]) -> list[dict]:
    s = summary(results)
    rows = []
    if path.exists():
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [r for r in rows if r["date"] != now.date().isoformat()]
    rows.append({"date": now.date().isoformat(), "rooms": s["rooms"], "ready": s["ready"], "ready_pct": s["ready_pct"]})
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return rows


def _trend(rows: list[dict]) -> str:
    rows = rows[-30:]
    if len(rows) < 2:
        return "<p class='muted'>Run the report on more days to see a trend.</p>"
    w, h, pad = 520, 120, 26
    xs = [pad + (w - 2 * pad) * i / (len(rows) - 1) for i in range(len(rows))]
    ys = [h - pad - (h - 2 * pad) * r["ready_pct"] / 100 for r in rows]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    dots = "".join(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='3'><title>{e(r['date'])}: {r['ready_pct']} %</title></circle>"
                   for x, y, r in zip(xs, ys, rows))
    grid = "".join(f"<line x1='{pad}' x2='{w - pad}' y1='{h - pad - (h - 2 * pad) * v / 100:.1f}' "
                   f"y2='{h - pad - (h - 2 * pad) * v / 100:.1f}' class='grid'/>"
                   f"<text x='2' y='{h - pad - (h - 2 * pad) * v / 100 + 4:.1f}'>{v}%</text>" for v in (0, 50, 100))
    labels = (f"<text x='{xs[0]:.1f}' y='{h - 6}' text-anchor='start'>{e(rows[0]['date'])}</text>"
              f"<text x='{xs[-1]:.1f}' y='{h - 6}' text-anchor='end'>{e(rows[-1]['date'])}</text>")
    return (f"<svg viewBox='0 0 {w} {h}' class='trend' role='img' aria-label='Share of rooms ready per day'>"
            f"{grid}<polyline points='{pts}'/>{dots}{labels}</svg>")


CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d2329;--muted:#66707a;--line:#e3e5e8;--ok:#1f7a4d;--warn:#a86400;--bad:#b42318;--accent:#2f5d8a}
@media (prefers-color-scheme:dark){:root{--bg:#14181c;--card:#1c2228;--ink:#e8eaed;--muted:#9aa4ae;--line:#2c343c;--ok:#4cc38a;--warn:#f0a83a;--bad:#f2685c;--accent:#7fb0e0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 18px 60px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 12px}
.muted{color:var(--muted)}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.tile b{display:block;font-size:28px}
.tile.ok b{color:var(--ok)}.tile.warn b{color:var(--warn)}.tile.bad b{color:var(--bad)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
tr:last-child td{border-bottom:0}.pill{display:inline-block;white-space:nowrap;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid currentColor}
.pill.ok{color:var(--ok)}.pill.warn{color:var(--warn)}.pill.bad{color:var(--bad)}.prio{font-size:11px;font-weight:700;color:var(--accent);margin-left:6px}
ul.issues{margin:0;padding-left:18px}ul.issues li.info{color:var(--muted)}.wrap{overflow-x:auto}
.trend{width:100%;max-width:560px;background:var(--card);border:1px solid var(--line);border-radius:10px}
.trend polyline{fill:none;stroke:var(--accent);stroke-width:2}.trend circle{fill:var(--accent)}.trend .grid{stroke:var(--line)}.trend text{font-size:10px;fill:var(--muted)}
footer{margin-top:40px;font-size:13px}
"""


def render_html(results: list[RoomResult], now: datetime, title: str, history: list[dict]) -> str:
    s = summary(results)
    tiles = (f"<div class='tile'><span class='muted'>Rooms</span><b>{s['rooms']}</b></div>"
             f"<div class='tile ok'><span class='muted'>Ready</span><b>{s['ready_pct']}%</b></div>"
             f"<div class='tile warn'><span class='muted'>At risk</span><b>{s['at_risk']}</b></div>"
             f"<div class='tile bad'><span class='muted'>Not ready</span><b>{s['not_ready']}</b></div>"
             f"<div class='tile bad'><span class='muted'>Priority rooms not ready</span><b>{s['priority_not_ready']}</b></div>")

    rows = []
    for r in results:
        if r.readiness == READY:
            continue
        issues = "".join(f"<li class='{i.severity}'>{e(i.text)}</li>" for i in r.issues)
        prio = "<span class='prio'>PRIORITY</span>" if r.room.priority else ""
        rows.append(f"<tr><td><b>{e(r.room.name)}</b>{prio}<br><span class='muted'>{e(r.room.site)} {e(r.room.floor)}</span></td>"
                    f"<td><span class='pill {STATE_CLASS[r.readiness]}'>{r.readiness}</span></td>"
                    f"<td><ul class='issues'>{issues}</ul></td><td>{_hm(r.next_meeting)}</td>"
                    f"<td>{e(r.device.manufacturer)} {e(r.device.model)}</td></tr>")
    attention = ("<div class='wrap'><table><thead><tr><th>Room</th><th>State</th><th>Issues</th><th>Next meeting (UTC)</th>"
                 f"<th>Device</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>") if rows else \
        "<p>All rooms ready.</p>"

    info = [(r, i) for r in results for i in r.issues if i.severity == "info"]
    house = ("<ul>" + "".join(f"<li><b>{e(r.room.name)}</b>: {e(i.text)}. <span class='muted'>{e(i.first_step)}</span></li>"
                             for r, i in info) + "</ul>") if info else "<p class='muted'>Nothing to tidy up.</p>"

    by_site: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        by_site[r.room.site or "Not registered"][r.readiness] += 1
    site_rows = "".join(
        f"<tr><td>{e(site)}</td><td>{sum(c.values())}</td><td>{c[READY]}</td><td>{c[AT_RISK]}</td><td>{c[NOT_READY]}</td>"
        f"<td>{round(100 * c[READY] / sum(c.values()))}%</td></tr>" for site, c in sorted(by_site.items()))

    versions: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for r in results:
        for sw in r.device.software:
            if sw.name in ("Teams Rooms app", "Firmware") and sw.current:
                versions[(f"{r.device.manufacturer} {r.device.model}", sw.name)][sw.current] += 1
    ver_rows = "".join(
        f"<tr><td>{e(model)}</td><td>{e(name)}</td><td>"
        + ", ".join(f"{e(v)} <span class='muted'>×{n}</span>" for v, n in c.most_common()) + "</td></tr>"
        for (model, name), c in sorted(versions.items()))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{CSS}</style></head><body><main>
<h1>{e(title)}</h1><p class="muted">Generated {now:%Y-%m-%d %H:%M} UTC · readiness of every Teams Rooms device before the day starts</p>
<div class="tiles">{tiles}</div>
<h2>Needs attention</h2><p class="muted">Ordered for the walk-round: not ready first, then priority rooms, then the next meeting.</p>
{attention}
<h2>Housekeeping</h2><p class="muted">Does not stop a meeting today, but worth fixing this week.</p>
{house}
<h2>By site</h2><div class="wrap"><table><thead><tr><th>Site</th><th>Rooms</th><th>Ready</th><th>At risk</th><th>Not ready</th><th>Ready %</th></tr></thead><tbody>{site_rows}</tbody></table></div>
<h2>Ready rooms over time</h2>{_trend(history)}
<h2>Versions in use</h2><p class="muted">More than one version per model usually means an update wave that did not finish.</p>
<div class="wrap"><table><thead><tr><th>Model</th><th>Software</th><th>Versions (devices)</th></tr></thead><tbody>{ver_rows}</tbody></table></div>
<footer class="muted">Teams Rooms Fleet Health · github.com/inigogonzalezgarcia/17-teams-rooms-fleet-health</footer>
</main></body></html>
"""
