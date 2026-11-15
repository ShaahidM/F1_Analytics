# F1 Telemetry Lab

A local engineering tool for comparing two Formula 1 drivers in historical Race and Qualifying sessions (2019 to present).
It covers telemetry aligned by track distance, braking and throttle behaviour, corner analysis and tyre-management indicators.

- **Data:** OpenF1 (2023+, full telemetry), Jolpica-F1 (2019–2022, lap times and pit stops only), MultiViewer (corner positions).
  See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) for what is and isn't publicly measurable.
- **Method:** [docs/TYRE_METHODOLOGY.md](docs/TYRE_METHODOLOGY.md). Every metric is labelled Measured / Calculated / Estimated / Interpretation.
- **Architecture:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Run

```bash
# Backend (Python 3.13)
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Frontend (Node 22+)
cd frontend
npm install
npm run dev   # http://localhost:3000
```

Downloaded data is cached under `data/` (gitignored, safe to delete).

## What it does

- **Session analysis** (race, sprint, qualifying, practice): lap comparison with animated replay and a
  corner-by-corner table, lap overlays, tyre degradation with a race-wide model, driving style, pace vs
  preservation, and strategy (pit stops, undercuts, cross-compound pace).
- **Season comparison**: the same two drivers race by race across a season, with a scorecard.

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest -q      # offline unit tests
cd frontend && npx playwright test                   # end-to-end, uses installed Microsoft Edge
```
