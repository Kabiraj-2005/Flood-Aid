# FloodAid — working model, step 1

The thin path: a report is filed with no network, held on the phone,
uploaded by itself when signal returns, and appears in the control room.

Nothing else matters until this runs. Build on top of it, not beside it.

## Run

    pip install fastapi uvicorn python-multipart
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

Open http://localhost:8000 on your laptop, or
http://<your-laptop-ip>:8000 on a phone connected to the same wifi.

## Try the thing that matters

1. Open the app, fill a report, press Save. It appears under "Waiting to upload".
2. Press "Simulate going offline". File two more. They queue.
3. Press "Simulate coming back online". Watch the queue empty.
4. `curl localhost:8000/api/reports` — they are all there, once each.

Then do it for real: put the phone in airplane mode instead of pressing
the button. That is the demo.

## Test

    python3 test_thin_path.py

Checks that the same report uploaded four times creates one row, that two
phones editing different fields offline both keep their change, that delta
sync returns nothing when the cursor is current, and that a phone with a
broken clock cannot jump the queue.

## Files

    backend/db.py        the agreed report schema. Do not rename a column
                         without telling the whole team.
    backend/main.py      upload (idempotent), delta sync, merge, list
    backend/severity.py  the visible severity formula
    web/outbox.js        the offline queue. This file is the project.
    web/index.html       the field report form

## Two bugs already found and fixed

Keep these in mind, they will come up in Q&A:

1. **Phone clocks lie.** Waiting time was computed from the phone's own
   timestamp, so a device with a wrong clock scored as having waited for
   decades and would have starved every real incident. Waiting now starts
   no earlier than the moment the server first saw the report, and is
   capped at 24 hours.

2. **A stale copy silently undid a fix.** Both phones send the whole
   record, so the server could not tell "I did not touch this field" from
   "I set it back to the old value". Phones now name the fields they
   actually edited.

## Next, in this order

3. clustering + confidence + decay
4. contradiction hold
5. zones -> remove crossing roads -> route
6. dispatch with capacity and return legs
7. drone polygon ingest
8. polish
