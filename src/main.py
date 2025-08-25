"""
AIA Flexible Graph - Multi-Instrument Redis Data Visualization

A flexible, config-driven Dash application for visualizing live multi-instrument 
data from Redis with dynamic layouts, selectable fields, dual y-axes, and customizable styling.

This module provides:
- Real-time data visualization from Redis
- Multi-instrument support with independent controls
- Configurable styling and display options
- In-memory data caching beyond Redis TTL
- Pause/resume and time-windowing functionality

Author: AIA Team
Date: 2025
"""

# Standard library imports
import json
import datetime
import os
from threading import Lock
import textwrap
from html import escape as html_escape

# Third-party imports
import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import plotly.graph_objs as go
import redis

# Configuration directory resolution
# Resolve config directory at repo root (../config relative to this file)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_DIR = os.path.join(os.path.dirname(_THIS_DIR), 'config')


def _cfg(name: str) -> str:
	"""
	Build configuration file paths.
	
	Args:
		name: Configuration filename (e.g., 'main.json')
		
	Returns:
		Absolute path to the configuration file
	"""
	return os.path.join(_CONFIG_DIR, name)

# Main configuration loading
# Load main configuration once at startup with fallback to defaults
MAIN_CONFIG = {}
try:
	with open(_cfg('main.json'), 'r', encoding='utf-8') as f:
		_main_data = json.load(f)
		if isinstance(_main_data, dict):
			MAIN_CONFIG = _main_data
except Exception:
	# Silently fall back to defaults if config file is missing or invalid
	MAIN_CONFIG = {}

# Application configuration with fallback defaults
REDIS_KEY_PATTERN = MAIN_CONFIG.get('redis_key_pattern', 'price_data:*:*')  # Redis key pattern to scan
APP_PORT = MAIN_CONFIG.get('app_port', 8051)  # Port for the Dash application
REDIS_PORT = MAIN_CONFIG.get('redis_port', 6379)  # Redis server port


def get_instrument_key_prefix(instrument: str) -> str:
	"""
	Build instrument-specific key prefix from the configured Redis key pattern.
	
	This function extracts the prefix pattern and substitutes the instrument name
	to create a prefix for filtering keys specific to that instrument.
	
	Args:
		instrument: Instrument identifier (e.g., 'EUR_USD')
		
	Returns:
		Key prefix string for the instrument (e.g., 'price_data:EUR_USD:')
		
	Example:
		For pattern "price_data:*:*" and instrument "EUR_USD",
		returns "price_data:EUR_USD:"
	"""
	# Extract the prefix pattern (everything before the first *)
	pattern_parts = REDIS_KEY_PATTERN.split('*')
	if len(pattern_parts) >= 2:
		prefix = pattern_parts[0] + instrument + ':'
		return prefix
	# Fallback if pattern is malformed
	return f"price_data:{instrument}:"

# Redis connection
redis_client = redis.Redis(host='localhost', port=REDIS_PORT, db=0, decode_responses=True)

# Global data storage and synchronization
# In-memory history to keep received data beyond Redis TTL per instrument
MEMORY_POINTS = {}  # Dict[str, List[dict]] - keyed by instrument name
SEEN_KEYS = set()   # Set[str] - tracks processed Redis keys to avoid duplicates
MEM_LOCK = Lock()   # Thread lock for synchronizing access to shared data structures
MAX_POINTS = 10000  # Maximum data points per instrument to prevent unbounded memory growth

# UI state tracking
# Store to track current instruments and prevent unnecessary layout updates
CURRENT_INSTRUMENTS = set()  # Set[str] - currently displayed instrument names

# Configuration loading section
# Load all configuration files once at startup with error handling

# Y-axis assignment configuration (y vs y2)
AXES_MAP = {}
try:
	with open(_cfg('axes.json'), 'r', encoding='utf-8') as f:
		_axes_data = json.load(f)
		if isinstance(_axes_data, dict):
			AXES_MAP = {str(k): str(v) for k, v in _axes_data.items()}
except Exception:
	# Use empty dict if config file is missing or invalid
	AXES_MAP = {}

# Display modes configuration (lines, markers, etc.)
MODES_MAP = {}
try:
	with open(_cfg('modes.json'), 'r', encoding='utf-8') as f:
		_modes_data = json.load(f)
		if isinstance(_modes_data, dict):
			# Validate modes against allowed Plotly modes
			_allowed_modes = {
				'lines', 'markers', 'lines+markers', 'none', 'text',
				'lines+text', 'markers+text', 'lines+markers+text'
			}
			MODES_MAP = {
				str(k): (str(v) if str(v) in _allowed_modes else 'lines+markers')
				for k, v in _modes_data.items()
			}
except Exception:
	MODES_MAP = {}

# Marker styling configuration
MARKERS_MAP = {}
try:
	with open(_cfg('markers.json'), 'r', encoding='utf-8') as f:
		_markers_data = json.load(f)
		if isinstance(_markers_data, dict):
			# Keep as-is; Plotly accepts dict with size/color/symbol/line keys
			MARKERS_MAP = {str(k): v for k, v in _markers_data.items() if isinstance(v, dict)}
except Exception:
	MARKERS_MAP = {}

# Line styling configuration
LINES_MAP = {}
try:
	with open(_cfg('lines.json'), 'r', encoding='utf-8') as f:
		_lines_data = json.load(f)
		if isinstance(_lines_data, dict):
			# Keep as-is; Plotly accepts dict with color/width/dash keys for line
			LINES_MAP = {str(k): v for k, v in _lines_data.items() if isinstance(v, dict)}
except Exception:
	LINES_MAP = {}

# Tooltip field ordering configuration
TOOLTIP_FIELDS = []
try:
	with open(_cfg('tooltip.json'), 'r', encoding='utf-8') as f:
		_tooltip_data = json.load(f)
		if isinstance(_tooltip_data, dict) and isinstance(_tooltip_data.get('fields'), list):
			TOOLTIP_FIELDS = [str(x) for x in _tooltip_data['fields']]
except Exception:
	TOOLTIP_FIELDS = []

def fetch_data():
	"""
	Fetch new data from Redis and update in-memory storage.
	
	This function:
	1. Scans Redis for keys matching the configured pattern
	2. Processes only new keys to avoid duplicate data
	3. Parses JSON payloads and normalizes timestamps
	4. Stores data in memory with automatic cleanup when limits are exceeded
	
	Returns:
		Dict[str, List[dict]]: Dictionary mapping instrument names to sorted data points
		
	Thread Safety:
		Uses MEM_LOCK to ensure thread-safe access to shared data structures
	"""
	# Scan Redis for keys matching the configured pattern
	keys = redis_client.keys(REDIS_KEY_PATTERN)
	
	# Only fetch new keys to avoid re-adding duplicates
	new_keys = [k for k in keys if k not in SEEN_KEYS]
	
	for key in new_keys:
		# Attempt to retrieve the data for this key
		raw = redis_client.get(key)
		if not raw:
			# Mark as seen even if empty to avoid repeated attempts
			SEEN_KEYS.add(key)
			continue
			
		try:
			# Extract instrument name from key using the configured pattern
			# For pattern "price_data:*:*", split by ':' and take the second part
			pattern_parts = REDIS_KEY_PATTERN.split('*')
			if len(pattern_parts) >= 2:
				prefix = pattern_parts[0]
				# Remove prefix and split to get instrument
				key_without_prefix = key[len(prefix):]
				instrument_and_rest = key_without_prefix.split(':', 1)
				if instrument_and_rest:
					instrument = instrument_and_rest[0]
				else:
					SEEN_KEYS.add(key)
					continue
			else:
				# Fallback for malformed pattern - assume price_data:INSTRUMENT:timestamp
				key_parts = key.split(':')
				if len(key_parts) >= 3:
					instrument = key_parts[1]
				else:
					SEEN_KEYS.add(key)
					continue
			
			# Parse the JSON payload
			dp = json.loads(raw)
			
			# Normalize timestamp format - try multiple parsing strategies
			# Parse timestamp: prefer ISO formats (with 'T' and optional timezone),
			# fall back to older space-separated formats.
			ts_raw = dp.get('timestamp')
			if isinstance(ts_raw, str):
				# Try ISO format first (handles '2025-08-25T11:52:32.755024' and offsets)
				try:
					dp['timestamp'] = datetime.datetime.fromisoformat(ts_raw)
				except Exception:
					# Fall back to space-separated format with microseconds
					try:
						dp['timestamp'] = datetime.datetime.strptime(ts_raw, '%Y-%m-%d %H:%M:%S.%f')
					except Exception:
						# Fall back to space-separated format without microseconds
						dp['timestamp'] = datetime.datetime.strptime(ts_raw, '%Y-%m-%d %H:%M:%S')
			else:
				# Leave as-is (later checks will ignore non-datetime entries)
				pass
				
			# Extract numeric epoch from key suffix to use as a stable secondary sort key
			# This ensures consistent ordering even when timestamps are identical
			try:
				dp['_epoch_ms'] = int(key.rsplit(':', 1)[-1])
			except Exception:
				dp['_epoch_ms'] = 0
				
			# Thread-safe update of in-memory storage
			with MEM_LOCK:
				if instrument not in MEMORY_POINTS:
					MEMORY_POINTS[instrument] = []
				MEMORY_POINTS[instrument].append(dp)
				SEEN_KEYS.add(key)
				
				# Trim data if above maximum limit (after sorting by timestamp + epoch)
				if len(MEMORY_POINTS[instrument]) > MAX_POINTS:
					MEMORY_POINTS[instrument].sort(key=lambda x: (x.get('timestamp'), x.get('_epoch_ms', 0)))
					del MEMORY_POINTS[instrument][:-MAX_POINTS]
		except Exception:
			# Mark as seen even if parsing failed to avoid repeated attempts
			SEEN_KEYS.add(key)
			continue
			
	# Return sorted snapshots of memory for all instruments
	with MEM_LOCK:
		result = {}
		for instrument, points in MEMORY_POINTS.items():
			# Sort by timestamp with epoch as secondary key for stable ordering
			result[instrument] = sorted(points, key=lambda x: (x.get('timestamp'), x.get('_epoch_ms', 0)))
		return result

def get_instruments():
	"""
	Get list of all instruments in alphabetical order.
	
	This function ensures data is loaded and returns a sorted list
	of all instrument names currently available in memory.
	
	Returns:
		List[str]: Sorted list of instrument names
	"""
	fetch_data()  # Ensure data is loaded
	with MEM_LOCK:
		return sorted(MEMORY_POINTS.keys())


def get_numeric_fields_union(data_points):
	"""
	Extract all numeric field names from a list of data points.
	
	This function scans through all data points and identifies fields
	that contain numeric values (int or float), excluding timestamp fields.
	
	Args:
		data_points (List[dict]): List of data point dictionaries
		
	Returns:
		List[str]: Sorted list of numeric field names
	"""
	if not data_points:
		return []
	
	fields = set()
	for dp in data_points:
		for k, v in dp.items():
			# Skip timestamp field and internal fields
			if k == 'timestamp':
				continue
			# Only include numeric fields
			if isinstance(v, (int, float)):
				fields.add(k)
	return sorted(fields)

def create_instrument_section(instrument):
	"""
	Create a complete UI section for a single instrument.
	
	This function generates a Dash component hierarchy that includes:
	- Header with instrument name and controls
	- Time window controls (show last N minutes)
	- Pause/resume functionality
	- Clear data button
	- Field selector dropdown
	- Graph visualization area
	
	Args:
		instrument (str): Name of the instrument (e.g., 'EUR_USD')
		
	Returns:
		html.Div: Complete Dash component for the instrument section
	"""
	
	return html.Div([
		# Header section for this instrument with controls
		html.Div([
			html.H3(f"{instrument}", style={'margin': 0, 'fontSize': '18px', 'fontWeight': 'bold'}),
			
			# Time window controls section
			html.Div([
				html.Label('Show last (minutes):', style={'marginRight': '6px', 'fontSize': '12px'}),
				dcc.Input(
					id={'type': 'minutes-input', 'instrument': instrument}, 
					type='number', 
					min=0, 
					value=0, 
					placeholder='0 = all', 
					style={'width': '100px'}
				),
				html.Button('Apply', id={'type': 'apply-button', 'instrument': instrument}, n_clicks=0, style={'marginLeft': '6px'}),
			], style={'display': 'flex', 'alignItems': 'center'}),
			
			# Hidden data stores for maintaining state across callbacks
			dcc.Store(id={'type': 'display-store', 'instrument': instrument}, data=0),
			dcc.Store(id={'type': 'paused-store', 'instrument': instrument}, data=False),
			dcc.Store(id={'type': 'pause-ref-store', 'instrument': instrument}, data=None),
			
			# Hidden space toggle button (for keyboard shortcuts)
			html.Button(id={'type': 'space-toggle', 'instrument': instrument}, style={'display': 'none'}),
			
			# Control buttons
			html.Button('Pause', id={'type': 'pause-button', 'instrument': instrument}, n_clicks=0, style={'marginLeft': '8px'}),
			html.Button('Clear data', id={'type': 'clear-button', 'instrument': instrument}, n_clicks=0, style={'margin':'8px'}),
			
			# Status output areas
			html.Div(id={'type': 'clear-output', 'instrument': instrument}, style={'color': 'green', 'marginBottom': '8px'}),
			html.Div(id={'type': 'display-output', 'instrument': instrument}, style={'color': 'blue', 'marginBottom': '8px'}),
			html.Div(id={'type': 'pause-output', 'instrument': instrument}, style={'color': 'purple', 'marginBottom': '8px'}),
		], style={'padding': '8px', 'flex': '0 0 auto', 'display': 'flex', 'alignItems': 'center', 'gap': '12px', 'borderBottom': '1px solid #ddd'}),

		# Field selector dropdown for this instrument
		html.Div([
			dcc.Dropdown(
				id={'type': 'fields-dropdown', 'instrument': instrument},
				multi=True,
				placeholder=f'Select fields for {instrument}',
				style={'width': '100%', 'fontSize': '12px'}
			),
		], style={'padding': '2px 2px', 'flex': '0 0 auto', 'width': '100%'}),

		# Graph visualization area for this instrument
		html.Div([
			dcc.Graph(id={'type': 'graph', 'instrument': instrument}, style={'height': '100%', 'width': '100%'}),
		], style={'flex': '1 1 auto', 'minHeight': 0, 'marginBottom': '0px', 'padding': '0px'}),

	], style={'height': '100vh', 'display': 'flex', 'flexDirection': 'column', 'marginBottom': '0'})


# Dash application initialization
app = dash.Dash(__name__)

# Font stack for consistent typography across the application
_FONT_STACK = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'

# Main application layout
app.layout = html.Div([
	# Application header
	html.Div([
		html.H2("Flexible Graph - Multi Instrument", style={'margin': 0, 'fontSize': '20px', 'textAlign': 'center'}),
		# Interval component for automatic data refresh (500ms polling)
		dcc.Interval(id='interval', interval=500, n_intervals=0),
	], style={'padding': '12px', 'backgroundColor': '#f8f9fa', 'borderBottom': '2px solid #dee2e6'}),

	# Dynamic container for all instrument sections
	html.Div(id='instruments-container', children=[]),

], style={'fontFamily': _FONT_STACK, 'padding': '0', 'margin': '0', 'height': '100vh', 'display': 'flex', 'flexDirection': 'column'})

# Dash callback functions
# These callbacks handle dynamic UI updates and user interactions

@app.callback(
	Output('instruments-container', 'children'),
	Input('interval', 'n_intervals')
)
def update_instruments_layout(n):
	"""
	Dynamically create and update instrument sections in the UI.
	
	This callback:
	- Runs on every interval tick (500ms)
	- Checks for new instruments in the data
	- Creates new UI sections only when instruments change
	- Avoids unnecessary layout updates for performance
	
	Args:
		n (int): Number of interval ticks (unused but required by Dash)
		
	Returns:
		List[html.Div] or dash.no_update: List of instrument sections or no update
	"""
	global CURRENT_INSTRUMENTS
	instruments = get_instruments()
	new_instruments = set(instruments)
	
	# Only update layout if instruments have changed to avoid unnecessary re-renders
	if new_instruments == CURRENT_INSTRUMENTS:
		return dash.no_update
	
	CURRENT_INSTRUMENTS = new_instruments
	
	# Handle case where no instruments are available yet
	if not instruments:
		return [html.Div(
			"No instruments found. Waiting for data...", 
			style={'textAlign': 'center', 'padding': '50px', 'fontSize': '16px', 'color': '#666'}
		)]
	
	# Create a section for each instrument
	sections = []
	for instrument in instruments:
		section = create_instrument_section(instrument)
		sections.append(section)
	
	return sections

# Pattern-matching callbacks for dynamic instrument interactions
@app.callback(
	Output({'type': 'fields-dropdown', 'instrument': dash.dependencies.MATCH}, 'options'),
	Output({'type': 'fields-dropdown', 'instrument': dash.dependencies.MATCH}, 'value'),
	Input('interval', 'n_intervals'),
	State({'type': 'fields-dropdown', 'instrument': dash.dependencies.MATCH}, 'value'),
	State({'type': 'fields-dropdown', 'instrument': dash.dependencies.MATCH}, 'id'),
)
def update_fields(n, current_value, component_id):
	"""
	Update field selector options for each instrument.
	
	This callback:
	- Runs on every interval for each instrument independently
	- Updates dropdown options based on available numeric fields
	- Preserves selected fields when possible
	- Automatically selects all fields for new instruments
	
	Args:
		n (int): Number of interval ticks
		current_value (List[str]): Currently selected field names
		component_id (dict): Component ID containing instrument name
		
	Returns:
		Tuple[List[dict], List[str]]: (dropdown options, selected values)
	"""
	instrument = component_id['instrument']
	all_data = fetch_data()
	data_points = all_data.get(instrument, [])
	
	# Get all numeric fields, excluding internal fields
	fields = get_numeric_fields_union(data_points)
	fields = [f for f in fields if f != '_epoch_ms']  # Exclude internal sorting field
	
	# Convert to dropdown options format
	options = [{'label': f, 'value': f} for f in fields]
	
	if current_value:
		# Preserve existing selections that are still valid
		new_value = [f for f in current_value if f in fields]
		return options, new_value
	
	# For new instruments, select all available fields by default
	return options, fields

@app.callback(
	Output({'type': 'display-store', 'instrument': dash.dependencies.MATCH}, 'data'),
	Input({'type': 'apply-button', 'instrument': dash.dependencies.MATCH}, 'n_clicks'),
	State({'type': 'minutes-input', 'instrument': dash.dependencies.MATCH}, 'value'),
)
def apply_display_window(n_clicks, minutes_value):
	"""
	Handle time window filtering controls.
	
	This callback processes the "Apply" button for time window controls,
	storing the number of minutes to display in the component's data store.
	
	Args:
		n_clicks (int): Number of times Apply button was clicked
		minutes_value (float): Number of minutes to display (0 = all data)
		
	Returns:
		float or dash.no_update: Minutes value to store, or no update if not clicked
	"""
	if not n_clicks:
		return dash.no_update
	
	try:
		minutes = float(minutes_value) if minutes_value is not None else 0
	except Exception:
		# Invalid input - no update
		return dash.no_update
	
	# Ensure non-negative values
	return max(0, minutes)

@app.callback(
	Output({'type': 'paused-store', 'instrument': dash.dependencies.MATCH}, 'data'),
	Output({'type': 'pause-ref-store', 'instrument': dash.dependencies.MATCH}, 'data'),
	Output({'type': 'pause-button', 'instrument': dash.dependencies.MATCH}, 'children'),
	Input({'type': 'space-toggle', 'instrument': dash.dependencies.MATCH}, 'n_clicks'),
	Input({'type': 'pause-button', 'instrument': dash.dependencies.MATCH}, 'n_clicks'),
	State({'type': 'paused-store', 'instrument': dash.dependencies.MATCH}, 'data'),
	State({'type': 'pause-button', 'instrument': dash.dependencies.MATCH}, 'id'),
)
def toggle_pause(n_space_clicks, n_visible_clicks, paused, component_id):
	"""
	Handle pause/resume functionality for real-time data updates.
	
	This callback manages the pause state for each instrument, allowing users
	to freeze the display at a specific point in time. When paused, it captures
	a reference timestamp to maintain consistent data filtering.
	
	Args:
		n_space_clicks (int): Hidden space button clicks (for keyboard shortcuts)
		n_visible_clicks (int): Visible pause button clicks
		paused (bool): Current pause state
		component_id (dict): Component ID containing instrument name
		
	Returns:
		Tuple[bool, str, str]: (new_paused_state, reference_timestamp_iso, button_label)
	"""
	if not n_space_clicks and not n_visible_clicks:
		return dash.no_update, dash.no_update, dash.no_update

	instrument = component_id['instrument']
	new_paused = not bool(paused)
	ref_iso = None
	
	if new_paused:
		# When pausing, capture the latest timestamp as reference
		all_data = fetch_data()
		data_points = all_data.get(instrument, [])
		with MEM_LOCK:
			latest = None
			# Find the most recent timestamp in the data
			for dp in data_points:
				ts = dp.get('timestamp')
				if isinstance(ts, datetime.datetime):
					if latest is None or ts > latest:
						latest = ts
		
		# Store reference timestamp in ISO format for consistency
		if latest is not None:
			ref_iso = latest.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
		button_label = 'Resume'
	else:
		# When resuming, clear the reference timestamp
		button_label = 'Pause'
	
	return new_paused, ref_iso, button_label

@app.callback(
	Output({'type': 'graph', 'instrument': dash.dependencies.MATCH}, 'figure'),
	Input({'type': 'fields-dropdown', 'instrument': dash.dependencies.MATCH}, 'value'),
	Input('interval', 'n_intervals'),
	Input({'type': 'paused-store', 'instrument': dash.dependencies.MATCH}, 'data'),
	State({'type': 'display-store', 'instrument': dash.dependencies.MATCH}, 'data'),
	State({'type': 'pause-ref-store', 'instrument': dash.dependencies.MATCH}, 'data'),
	State({'type': 'graph', 'instrument': dash.dependencies.MATCH}, 'id'),
)
def update_graph(selected_fields, n, paused, display_minutes, pause_ref_iso, component_id):
	"""
	Update the graph visualization for an instrument.
	
	This is the main visualization callback that handles:
	- Field selection and filtering
	- Real-time data updates with pause/resume functionality
	- Time window filtering (show last N minutes)
	- Dual y-axis support
	- Custom styling from configuration files
	- Interactive hover tooltips with wrapped text
	
	Args:
		selected_fields (List[str]): List of selected field names to display
		n (int): Number of interval ticks
		paused (bool): Whether updates are paused for this instrument
		display_minutes (float): Number of minutes to display (0 = all)
		pause_ref_iso (str): Reference timestamp when paused (ISO format)
		component_id (dict): Component ID containing instrument name
		
	Returns:
		plotly.graph_objs.Figure: Updated Plotly figure or dash.no_update
	"""
	if not selected_fields:
		# Return empty figure if no fields selected
		return go.Figure()
	
	instrument = component_id['instrument']
	# Filter out internal fields that shouldn't be displayed
	selected_fields = [f for f in selected_fields if f != '_epoch_ms']
	all_data = fetch_data()
	data_points = all_data.get(instrument, [])
	
	# Pause functionality: prevent updates during pause state when triggered by interval
	trigger = None
	try:
		trig = dash.callback_context.triggered
		if trig:
			trigger = trig[0].get('prop_id')
	except Exception:
		trigger = None
		
	# If paused and triggered by interval, don't update the graph
	if paused and trigger and trigger.startswith('interval.'):
		return dash.no_update

	# Time filtering logic
	try:
		disp_minutes = float(display_minutes) if display_minutes is not None else 0
	except Exception:
		disp_minutes = 0
	
	# Handle pause reference timestamp
	ref_ts = None
	if paused and pause_ref_iso and data_points:
		try:
			ref_ts = datetime.datetime.strptime(pause_ref_iso, '%Y-%m-%d %H:%M:%S.%f')
		except Exception:
			ref_ts = None
			
		# When paused, only show data up to the pause reference time
		if ref_ts is not None:
			data_points = [dp for dp in data_points 
						  if isinstance(dp.get('timestamp'), datetime.datetime) 
						  and dp['timestamp'] <= ref_ts]

	# Apply time window filtering (show last N minutes)
	if disp_minutes > 0 and data_points:
		# Determine reference timestamp for windowing
		if ref_ts is None:
			# Use the latest timestamp in the data
			ref_ts_for_window = max(
				(dp.get('timestamp') for dp in data_points 
				 if isinstance(dp.get('timestamp'), datetime.datetime)), 
				default=None
			)
		else:
			# Use pause reference timestamp
			ref_ts_for_window = ref_ts
			
		if ref_ts_for_window is not None:
			# Calculate cutoff time and filter data
			cutoff = ref_ts_for_window - datetime.timedelta(minutes=disp_minutes)
			data_points = [dp for dp in data_points 
						  if isinstance(dp.get('timestamp'), datetime.datetime) 
						  and dp['timestamp'] >= cutoff]
	
	# Return empty figure if no data or fields remain after filtering
	if not data_points or not selected_fields:
		return go.Figure()

	# Extract timestamps for x-axis
	timestamps = [dp['timestamp'] for dp in data_points]
	
	# Build custom hover data for interactive tooltips
	# Use configured tooltip fields or default to basic fields
	fields_for_tooltip = TOOLTIP_FIELDS or ['timestamp', 'price']
	customdata = []
	
	for dp in data_points:
		per_point_lines = []
		for idx, fname in enumerate(fields_for_tooltip):
			# Add line breaks between fields (except for first field)
			prefix = '' if idx == 0 else '<br>'
			
			if fname == 'timestamp':
				# Format timestamp for display
				ts = dp.get('timestamp')
				if isinstance(ts, datetime.datetime):
					ts_str = ts.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
				else:
					ts_str = str(ts) if ts is not None else ''
				line = f"{prefix}<b>timestamp</b>: {html_escape(ts_str)}" if ts_str else ''
			else:
				# Handle other fields
				val = dp.get(fname)
				if val is None or val == '':
					line = ''
				else:
					if fname == 'description':
						# Special handling for description field - wrap long text
						safe = html_escape(str(val))
						wrapped = textwrap.fill(safe, width=60).replace('\n', '<br>')
						line = f"{prefix}<b>description</b>: {wrapped}"
					else:
						# Standard field formatting
						line = f"{prefix}<b>{html_escape(fname)}</b>: {html_escape(str(val))}"
			per_point_lines.append(line)
		customdata.append(per_point_lines)
	
	# Build hover template for Plotly
	hover_template = ''.join([f"%{{customdata[{i}]}}" for i in range(len(fields_for_tooltip))]) + "<extra></extra>"
	
	# Create Plotly figure
	fig = go.Figure()
	
	# Add traces for each selected field
	for field in selected_fields:
		values = [dp.get(field) for dp in data_points]
		
		# Determine y-axis assignment from configuration
		yaxis_ref = 'y2' if AXES_MAP.get(field) == 'y2' else 'y'
		
		# Get styling configuration for this field
		mode = MODES_MAP.get(field, 'lines')  # Default to lines mode
		marker_cfg = MARKERS_MAP.get(field)   # Custom marker styling
		line_cfg = LINES_MAP.get(field)       # Custom line styling
		
		# Build trace configuration
		trace_kwargs = dict(
			x=timestamps,
			y=values,
			mode=mode,
			name=field,
			yaxis=yaxis_ref,
			customdata=customdata,
			hovertemplate=hover_template,
		)
		
		# Apply custom styling if configured
		if isinstance(marker_cfg, dict):
			trace_kwargs['marker'] = marker_cfg
		if isinstance(line_cfg, dict):
			trace_kwargs['line'] = line_cfg
			
		fig.add_trace(go.Scatter(**trace_kwargs))
	
	# Configure figure layout and styling
	fig.update_layout(
		title=None,  # No title to maximize chart space
		xaxis_title=None,  # No axis titles for cleaner look
		yaxis_title=None,
		legend_title=None,
		# Position legend horizontally at top
		legend=dict(orientation='h', y=1.02, yanchor='bottom', x=0.5, xanchor='center'),
		# Optimize margins for maximum chart area
		margin=dict(l=40, r=40, t=60, b=40),
		# Clean color scheme
		paper_bgcolor='white',
		plot_bgcolor='white',
		# Grid styling for better readability
		xaxis=dict(showgrid=True, gridcolor='lightgray', zeroline=False, showline=False),
		yaxis=dict(showgrid=True, gridcolor='lightgray', zeroline=False, showline=False),
	)
	
	# Configure hover label styling
	fig.update_layout(hoverlabel=dict(bgcolor='white', font=dict(color='black')))
	
	# Add secondary y-axis if any fields are configured to use it
	if any(AXES_MAP.get(f) == 'y2' for f in selected_fields):
		fig.update_layout(
			yaxis2=dict(title=None, overlaying='y', side='right', showgrid=False)
		)
		
	return fig

@app.callback(
	Output({'type': 'clear-output', 'instrument': dash.dependencies.MATCH}, 'children'),
	Input({'type': 'clear-button', 'instrument': dash.dependencies.MATCH}, 'n_clicks'),
	State({'type': 'clear-button', 'instrument': dash.dependencies.MATCH}, 'id'),
)
def clear_data(n_clicks, component_id):
	"""
	Clear all cached data for a specific instrument.
	
	This callback handles the "Clear data" button functionality:
	- Removes all in-memory data points for the instrument
	- Clears the seen keys cache for the instrument
	- Uses the configurable Redis key pattern for accurate cleanup
	
	Args:
		n_clicks (int): Number of times the clear button was clicked
		component_id (dict): Component ID containing instrument name
		
	Returns:
		dash.no_update: Always returns no update (no visual feedback currently)
	"""
	if not n_clicks:
		return dash.no_update
		
	instrument = component_id['instrument']
	
	with MEM_LOCK:
		# Remove all data points for this instrument
		if instrument in MEMORY_POINTS:
			del MEMORY_POINTS[instrument]
			
		# Remove all seen keys for this instrument using configurable pattern
		instrument_prefix = get_instrument_key_prefix(instrument)
		keys_to_remove = {k for k in SEEN_KEYS if k.startswith(instrument_prefix)}
		SEEN_KEYS.difference_update(keys_to_remove)
		
	return dash.no_update


# Application entry point
if __name__ == "__main__":
	"""
	Start the Dash application server.
	
	The application will:
	- Run in debug mode for development
	- Use the port configured in main.json (default: 8051)
	- Be accessible at http://localhost:<APP_PORT>
	"""
	app.run(debug=True, port=APP_PORT)
