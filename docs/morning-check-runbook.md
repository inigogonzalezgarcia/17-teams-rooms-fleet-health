# Runbook: morning check of meeting rooms

A short routine for the engineer on site before the first meetings. The goal is simple: nobody should find out that a room is broken by walking into it with a client.

## When

Every working day, 60–90 minutes before the first meetings (earlier on board or committee days).

## Steps

1. **Run the report** (or let a scheduled task run it):
   ```powershell
   .\scripts\Export-TeamsRoomsHealth.ps1 -OutputPath .\teams_rooms_health.json
   .\scripts\Export-RoomBookings.ps1 -RoomsCsv .\rooms.csv -OutputPath .\bookings.csv   # optional
   python -m rooms_health report teams_rooms_health.json --rooms rooms.csv --bookings bookings.csv --history history.jsonl
   ```
2. **Open `output/morning_check.md`** and work top to bottom. The order already accounts for readiness, priority rooms and the next meeting.
3. **For each room:** go there, apply the first step written next to the issue, then start a test call from the console (camera, microphone, speaker, content sharing).
4. **If it cannot be fixed before the meeting:**
   - Tell the organiser and offer a ready room of the same size (the report lists them by site).
   - For a priority room, stay for the first five minutes of the meeting or have a laptop with a USB conference kit ready as a fallback.
   - Open a ticket with the device serial number (in `actions.csv`) and, for hardware, the vendor case.
5. **Close the loop:** run the report again after the round. The trend chart should show the day's readiness.

## Before a board or committee meeting

- Check the room the day before and again one hour before.
- Do not install updates on a priority room on a meeting day. Updates go in the maintenance window, then the room is tested.
- Keep spare cables (HDMI, USB-C, USB-A/B) and a known-good laptop in the room cabinet.

## Weekly

- Clear the **Housekeeping** list: firmware drift and rooms missing from the register.
- Review the **Versions in use** table. More than one version per model means an update wave did not finish.
- Look at the trend. A room that appears in the list three days in a row needs a proper fix, not another restart.
