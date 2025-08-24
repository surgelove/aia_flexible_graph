# aia_flexible_graph

Flexible, config-driven Dash app that visualizes live data from Redis with selectable fields, dual y-axes, and customizable styling and tooltips.

## Overview

The app reads JSON payloads from Redis keys matching `price_data:USD_JPY:*`, keeps a rolling in-memory history, and renders them in a Plotly graph. You can:

- Pick which numeric fields to display via a dropdown.
- Map selected series to a secondary y-axis (y2) using `config/axes.json`.
- Customize trace modes, marker styles, and line styles via `config/*.json`.
- Configure hover tooltips via `config/tooltip.json`.

The repository also includes two small utilities under `test/` to generate or manually inject test data into Redis while you view the graph.

## Prerequisites

- Python 3.8+
- Redis running locally on `localhost:6379`

Install Python dependencies (example):

```
pip3 install dash plotly redis
```

Start Redis on macOS (either works):

```
# Homebrew service (recommended)
brew services start redis

# Or run directly (foreground)
redis-server
```

## Run the graph app

```
python3 src/graph.py
```

Then open http://localhost:8051.

Notes:

- The app polls Redis for keys named `price_data:USD_JPY:*` and stores recent points beyond Redis TTL (capped at 10,000).
- The field dropdown auto-populates from numeric fields observed in the data.
- A field will render on the right-hand axis if `config/axes.json` maps it to `"y2"`.

## Configuration

All configs live in the repository’s top-level `config/` folder and are loaded at startup:

- `axes.json`: Map field name to `"y"` or `"y2"` to place that series on the primary or secondary y-axis.
- `modes.json`: Map field name to a Plotly scatter mode, e.g. `"lines"`, `"markers"`, `"lines+markers"`, etc.
- `markers.json`: Per-field Plotly marker dict (e.g., `{ "size": 6, "color": "#1f77b4" }`).
- `lines.json`: Per-field Plotly line dict (e.g., `{ "width": 2, "dash": "dot" }`).
- `tooltip.json`: `{ "fields": ["timestamp", "price", "ema_short", ...] }` controls the order/content of hover text.

Example minimal `axes.json` to place a field on y2:

```
{
	"random_0_5": "y2"
}
```

## Data format (Redis values)

Each key should have a JSON value similar to:

```
{
	"timestamp": "YYYY-MM-DD HH:MM:SS.mmm",
	"price": 150.1234,
	"ema_short": 150.2345,
	"ema_long": 150.3456,
	"signal": "BULLISH_CROSS",        # optional
	"description": "...",             # optional
	"random_0_5": 3                    # optional example field
}
```

Keys must follow the pattern `price_data:USD_JPY:<epoch_ms>`.

## Using the test utilities

Two helpers under `test/` make it easy to feed data into Redis while you view the graph.

### 1) Automated generator and streamer

Runs a scenario that sends historical points and then streams live data; it also includes a signal-focused mode.

```
python3 test/test_graph.py
```

- Option 1 sends ~30 historical points, then starts live streaming. Open the graph at http://localhost:8051 to watch updates.
- Option 2 sends a predefined price path to trigger EMA crossover signals.
- Option 3 clears the matching Redis keys.

### 2) Manual sender UI

Launch a small Dash app that lets you craft payloads and submit them to Redis:

```
python3 test/test_graph_manual.py
```

Open http://localhost:8052 to set timestamp, price, EMAs, optional fields, and TTL; hit Submit to send. Keep the main graph running to see updates.

## Troubleshooting

- No data on the graph? Ensure Redis is running and the test utility is sending keys: `redis-cli keys 'price_data:USD_JPY:*'`.
- y2 axis not showing? Confirm `config/axes.json` exists at repo root and maps the field to `"y2"`. The app creates the right-hand axis only if any selected field is set to y2.
- Hover text odd or too long? Adjust `config/tooltip.json` (the `description` field is wrapped for readability).


