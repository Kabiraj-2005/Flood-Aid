# FloodAid — rules for anyone (or anything) editing this code

## The three claims we are judged on
1. Works with the network off
2. Routes around water, not through it
3. Never acts on a single unverified report

## Design rules that must not be broken
- Danger does NOT rise with silence. A quiet zone gets less certain, not
  more dangerous. Areas with no reports are UNKNOWN and stay uncoloured.
- Danger (how bad) and confidence (how sure) are separate axes. Never merge them.
- Report ids are generated on the phone, never the server.
- Saving a report never touches the network.
- Text uploads before photos.
- Severity is a visible formula, not a model.
- One device cannot confirm a zone alone. Aerial surveys are the exception.
- Held reports must not influence the danger level (two-pass, see danger.py).
- Tuning constants live at the top of danger.py and nowhere else.

## Do not
- Change the report schema without telling the whole team
- Tune thresholds to make the benchmark look better
- Cache the danger map (confidence decays with the clock)

## Run
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
    python3 test_thin_path.py
    python3 test_danger.py