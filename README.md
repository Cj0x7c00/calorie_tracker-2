# Macro & Weight Tracker (Flask + SQLite)

## Quickstart

```bash
cd calorie_tracker
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Optionally set environment vars via .env
python app.py
# Open http://127.0.0.1:5000
```

- The app stores data in `tracker.db` (SQLite).
- Set daily macro targets in **Settings**.
- Log foods on **Today** (or navigate dates), and log weights in **Weight**.
- Export your foods as CSV from the navbar.
