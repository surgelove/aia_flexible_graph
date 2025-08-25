# AIA Flexible Graph

A flexible, config-driven Dash application for visualizing live multi-instrument data from Redis with dynamic layouts, selectable fields, dual y-axes, and customizable styling.

![AIA Flexible Graph](images/FlexibleGraphExample.png
)

## Overview

This application automatically discovers and displays data for multiple instruments from Redis, creating a separate graph section for each instrument. The app:

- Dynamically creates instrument sections as new data arrives
- Provides independent field selection and controls for each instrument  
- Supports dual y-axes, customizable trace styling, and configurable tooltips
- Maintains rolling in-memory history beyond Redis TTL
- Offers pause/resume and time-windowing controls per instrument

## Prerequisites

- Python 3.8+
- Redis server running on `localhost:6379`

Install dependencies:
```bash
pip install dash plotly redis
```

Start Redis:
```bash
# macOS with Homebrew
brew services start redis

# Or run directly
redis-server
```

## Quick Start

1. Start the application:
```bash
python src/main.py
```

2. Open http://localhost:8051

3. Send test data using the included utilities (see Test Utilities section)

## Data Format

The app reads JSON data from Redis keys following the pattern: `price_data:INSTRUMENT:TIMESTAMP`

Example key: `price_data:EUR_USD:1640995200000`

Example JSON payload:
```json
{
  "timestamp": "2025-01-15T14:30:25.123",
  "price": 1.0850,
  "ema_short": 1.0845,
  "ema_long": 1.0860,
  "volume": 1250000,
  "signal": "BULLISH_CROSS",
  "description": "Strong upward momentum detected"
}
```

**Key Requirements:**
- Keys must follow `price_data:INSTRUMENT:TIMESTAMP` pattern
- JSON must include a `timestamp` field (ISO format preferred)
- Numeric fields will automatically appear in the field selector
- Each instrument gets its own section and controls

## Features

### Multi-Instrument Support
- Automatic instrument detection and section creation
- Independent controls for each instrument
- Alphabetically sorted instrument display

### Per-Instrument Controls
- **Field Selection**: Multi-select dropdown for numeric fields
- **Time Windowing**: Show last N minutes of data
- **Pause/Resume**: Freeze updates while maintaining data collection
- **Clear Data**: Remove all cached data for an instrument

### Visualization
- Plotly-powered interactive graphs with full viewport sections
- Configurable dual y-axes support
- Custom hover tooltips with wrapped descriptions
- Real-time updates (500ms polling interval)

## Configuration

All configuration files are located in the `config/` directory and loaded at startup:

### `config/axes.json` - Y-Axis Assignment
Maps fields to primary (`y`) or secondary (`y2`) y-axis:
```json
{
  "volume": "y2",
  "rsi": "y2",
  "price": "y",
  "ema_short": "y"
}
```

### `config/modes.json` - Display Modes
Controls how each field is rendered:
```json
{
  "price": "lines",
  "volume": "markers",
  "ema_short": "lines+markers"
}
```

Valid modes: `lines`, `markers`, `lines+markers`, `none`, `text`, `lines+text`, `markers+text`, `lines+markers+text`

### `config/markers.json` - Marker Styling
Customize marker appearance:
```json
{
  "price": {
    "size": 8,
    "color": "#1f77b4",
    "symbol": "circle"
  },
  "volume": {
    "size": 6,
    "color": "#ff7f0e",
    "symbol": "square"
  }
}
```

### `config/lines.json` - Line Styling
Customize line appearance:
```json
{
  "price": {
    "width": 2,
    "color": "#1f77b4"
  },
  "ema_short": {
    "width": 1,
    "dash": "dash",
    "color": "#2ca02c"
  }
}
```

### `config/tooltip.json` - Hover Information
Control tooltip content and order:
```json
{
  "fields": [
    "timestamp",
    "price",
    "ema_short", 
    "ema_long",
    "volume",
    "signal",
    "description"
  ]
}
```

## Test Utilities

### Automated Data Generator
Generate historical and live streaming data:
```bash
python test/test_graph.py
```

Options:
1. **Historical + Live**: Sends ~30 historical points then streams live data
2. **Signal Scenario**: Predefined price movements to trigger EMA crossovers  
3. **Clear Data**: Remove all test keys from Redis

### Manual Data Entry
Interactive web interface for crafting custom payloads:
```bash
python test/test_graph_manual.py
```

Open http://localhost:8052 to manually create and submit data points with custom timestamps, prices, and optional fields.

## Architecture

### Data Flow
1. **Polling**: App polls Redis every 500ms for `price_data:*:*` keys
2. **Parsing**: Extracts instrument name and parses JSON payload
3. **Storage**: Maintains in-memory history (max 10,000 points per instrument)
4. **Display**: Creates dynamic layout with per-instrument sections

### Memory Management
- Rolling window of up to 10,000 points per instrument
- Automatic cleanup of old data points
- Efficient incremental updates (only new keys processed)

### State Management
- Per-instrument pause/resume state
- Independent time window settings
- Field selection preserved during updates

## Troubleshooting

**No instruments appearing?**
- Verify Redis is running: `redis-cli ping`
- Check for data keys: `redis-cli keys 'price_data:*'`
- Run test utilities to generate sample data

**Secondary y-axis not showing?**
- Ensure `config/axes.json` exists and maps fields to `"y2"`
- Verify the mapped fields are selected in the dropdown
- Check that field names match exactly (case-sensitive)

**Performance issues with large datasets?**
- Data is capped at 10,000 points per instrument
- Use time windowing to display only recent data
- Consider pausing updates during intensive data loads

**Hover tooltips too verbose?**
- Adjust `config/tooltip.json` to include only needed fields
- Description fields are automatically wrapped at 60 characters

## Development

The application uses:
- **Dash**: Web framework with reactive callbacks
- **Plotly**: Interactive plotting library
- **Redis**: In-memory data store
- **Pattern-matching callbacks**: For dynamic multi-instrument support

Key files:
- `src/main.py`: Main application with multi-instrument layout
- `config/*.json`: Configuration files for styling and behavior
- `test/`: Utilities for generating test data


