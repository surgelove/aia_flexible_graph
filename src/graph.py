# Dash app to display Redis data with selectable fields
import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import plotly.graph_objs as go
import redis
import json
import datetime
import os
from threading import Lock
import textwrap
from html import escape as html_escape

# Redis connection
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# In-memory history to keep received data beyond Redis TTL
MEMORY_POINTS = []  # list[dict]
SEEN_KEYS = set()   # set[str]
MEM_LOCK = Lock()
MAX_POINTS = 10000  # cap history to prevent unbounded growth

# Resolve config directory at repo root (../config relative to this file)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_DIR = os.path.join(os.path.dirname(_THIS_DIR), 'config')

# Small helper to build config file paths
def _cfg(name: str) -> str:
    return os.path.join(_CONFIG_DIR, name)

# Load axes configuration once at startup
AXES_MAP = {}
try:
	with open(_cfg('axes.json'), 'r', encoding='utf-8') as f:
		_axes_data = json.load(f)
		if isinstance(_axes_data, dict):
			AXES_MAP = {str(k): str(v) for k, v in _axes_data.items()}
except Exception:
	AXES_MAP = {}

# Load modes configuration once at startup
MODES_MAP = {}
try:
	with open(_cfg('modes.json'), 'r', encoding='utf-8') as f:
		_modes_data = json.load(f)
		if isinstance(_modes_data, dict):
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

# Load markers configuration once at startup
MARKERS_MAP = {}
try:
	with open(_cfg('markers.json'), 'r', encoding='utf-8') as f:
		_markers_data = json.load(f)
		if isinstance(_markers_data, dict):
			# Keep as-is; Plotly accepts dict with size/color/symbol/line keys
			MARKERS_MAP = {str(k): v for k, v in _markers_data.items() if isinstance(v, dict)}
except Exception:
	MARKERS_MAP = {}

# Load lines configuration once at startup
LINES_MAP = {}
try:
	with open(_cfg('lines.json'), 'r', encoding='utf-8') as f:
		_lines_data = json.load(f)
		if isinstance(_lines_data, dict):
			# Keep as-is; Plotly accepts dict with color/width/dash keys for line
			LINES_MAP = {str(k): v for k, v in _lines_data.items() if isinstance(v, dict)}
except Exception:
	LINES_MAP = {}

# Load tooltip configuration once at startup
TOOLTIP_FIELDS = []
try:
	with open(_cfg('tooltip.json'), 'r', encoding='utf-8') as f:
		_tooltip_data = json.load(f)
		if isinstance(_tooltip_data, dict) and isinstance(_tooltip_data.get('fields'), list):
			TOOLTIP_FIELDS = [str(x) for x in _tooltip_data['fields']]
except Exception:
	TOOLTIP_FIELDS = []

def fetch_data():
	keys = redis_client.keys("price_data:USD_JPY:*")
	# Only fetch new keys to avoid re-adding duplicates
	new_keys = [k for k in keys if k not in SEEN_KEYS]
	for key in new_keys:
		raw = redis_client.get(key)
		if not raw:
			SEEN_KEYS.add(key)
			continue
		try:
			dp = json.loads(raw)
			# Parse timestamp (accept with or without milliseconds)
			try:
				dp['timestamp'] = datetime.datetime.strptime(dp['timestamp'], '%Y-%m-%d %H:%M:%S.%f')
			except ValueError:
				dp['timestamp'] = datetime.datetime.strptime(dp['timestamp'], '%Y-%m-%d %H:%M:%S')
			# Extract numeric epoch from key suffix to use as a stable secondary sort key
			try:
				dp['_epoch_ms'] = int(key.rsplit(':', 1)[-1])
			except Exception:
				dp['_epoch_ms'] = 0
			with MEM_LOCK:
				MEMORY_POINTS.append(dp)
				SEEN_KEYS.add(key)
				# Trim if above cap (after sorting by timestamp + epoch)
				if len(MEMORY_POINTS) > MAX_POINTS:
					MEMORY_POINTS.sort(key=lambda x: (x.get('timestamp'), x.get('_epoch_ms', 0)))
					del MEMORY_POINTS[:-MAX_POINTS]
		except Exception:
			SEEN_KEYS.add(key)
			continue
	# Return a sorted snapshot of memory for rendering
	with MEM_LOCK:
		return sorted(MEMORY_POINTS, key=lambda x: (x.get('timestamp'), x.get('_epoch_ms', 0)))

def get_numeric_fields_union(data_points):
    if not data_points:
        return []
    fields = set()
    for dp in data_points:
        for k, v in dp.items():
            if k == 'timestamp':
                continue
            if isinstance(v, (int, float)):
                fields.add(k)
    return sorted(fields)

app = dash.Dash(__name__)

_FONT_STACK = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'

app.layout = html.Div([
	# Header / controls area (fixed height)
	html.Div([
		html.H2("Flexible Graph", style={'margin': 0, 'fontSize': '16px'}),
		dcc.Interval(id='interval', interval=100, n_intervals=0),
		# fields-dropdown moved below to occupy full width above the graph
		# Display-window controls: choose a minutes window to display (does not delete data)
		html.Div([
			html.Label('Show last (minutes):', style={'marginRight': '6px', 'fontSize': '12px'}),
			dcc.Input(id='minutes-input', type='number', min=0, value=0, placeholder='0 = all', style={'width': '100px'}),
			html.Button('Apply', id='apply-window-button', n_clicks=0, style={'marginLeft': '6px'}),
		], style={'display': 'flex', 'alignItems': 'center'}),
		# hidden store to keep the currently applied display window in minutes
		dcc.Store(id='display-window-store', data=0),
		# store whether the graph is paused (true = freeze display at last timestamp)
		dcc.Store(id='paused-store', data=False),
		# store the reference timestamp (ISO string) captured when paused
		dcc.Store(id='pause-ref-store', data=None),
		# hidden button toggled by spacebar via assets/space_toggle.js
		html.Button(id='space-toggle-button', style={'display': 'none'}),
	# visible pause/resume button for discoverability (default label = Pause)
	html.Button('Pause', id='pause-toggle-visible', n_clicks=0, style={'marginLeft': '8px'}),
		html.Button('Clear data', id='clear-button', n_clicks=0, style={'margin':'8px'}),
		html.Div(id='clear-output', style={'color': 'green', 'marginBottom': '8px'}),
		html.Div(id='display-window-output', style={'color': 'blue', 'marginBottom': '8px'}),
		html.Div(id='pause-output', style={'color': 'purple', 'marginBottom': '8px'}),
	], style={'padding': '8px', 'flex': '0 0 auto', 'display': 'flex', 'alignItems': 'center', 'gap': '12px'}),

	# Fields selector full-width section directly above the graph
	html.Div([
		dcc.Dropdown(
			id='fields-dropdown',
			multi=True,
			placeholder='Select fields to display',
			style={'width': '100%', 'fontSize': '12px'}
		),
	], style={'padding': '6px 12px', 'flex': '0 0 auto', 'width': '97%'}),

	# Graph area fills remaining viewport height
	html.Div([
		dcc.Graph(id='live-graph', style={'height': '100%', 'width': '100%'}),
	], style={'flex': '1 1 auto', 'minHeight': 0}),

], style={'display': 'flex', 'flexDirection': 'column', 'height': '100vh', 'fontFamily': _FONT_STACK})

@app.callback(
	Output('fields-dropdown', 'options'),
	Output('fields-dropdown', 'value'),
	Input('interval', 'n_intervals'),
	State('fields-dropdown', 'value')
)
def update_fields(n, current_value):
	data_points = fetch_data()
	fields = get_numeric_fields_union(data_points)
	# Hide internal fields
	fields = [f for f in fields if f != '_epoch_ms']
	options = [{'label': f, 'value': f} for f in fields]
	# Preserve user selection; drop any fields that disappeared
	if current_value:
		new_value = [f for f in current_value if f in fields]
		return options, new_value
	# Default to all available numeric fields on first load
	return options, fields


@app.callback(
	Output('display-window-store', 'data'),
	Input('apply-window-button', 'n_clicks'),
	State('minutes-input', 'value')
)
def apply_display_window(n_clicks, minutes_value):
	"""Save the chosen display window in minutes into the Store.

	No UI message is displayed; the store is updated only.
	"""
	if not n_clicks:
		return dash.no_update
	try:
		minutes = float(minutes_value) if minutes_value is not None else 0
	except Exception:
		return dash.no_update
	if minutes <= 0:
		return 0
	return minutes


@app.callback(
	Output('paused-store', 'data'),
	Output('pause-ref-store', 'data'),
	Output('pause-toggle-visible', 'children'),
	Input('space-toggle-button', 'n_clicks'),
	Input('pause-toggle-visible', 'n_clicks'),
	State('paused-store', 'data')
)
def toggle_pause(n_space_clicks, n_visible_clicks, paused):
	"""Toggle paused state. When pausing, capture the latest timestamp seen in MEMORY_POINTS
	and store it in ISO format in `pause-ref-store`. When unpausing, clear the reference.
	"""
	# If neither button has been clicked yet, do nothing (don't overwrite initial label)
	if not n_space_clicks and not n_visible_clicks:
		return dash.no_update, dash.no_update, dash.no_update

	# flip paused flag
	new_paused = not bool(paused)
	ref_iso = None
	message = ''
	if new_paused:
		# capture latest timestamp
		with MEM_LOCK:
			latest = None
			for dp in MEMORY_POINTS:
				ts = dp.get('timestamp')
				if isinstance(ts, datetime.datetime):
					if latest is None or ts > latest:
						latest = ts
		if latest is not None:
			# store as ISO-like string for safe transport
			ref_iso = latest.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
			# button should indicate resume action when paused
			button_label = 'Resume'
		else:
			button_label = 'Resume'
	else:
		button_label = 'Pause'
	return new_paused, ref_iso, button_label

@app.callback(
	Output('live-graph', 'figure'),
	Input('fields-dropdown', 'value'),
	Input('interval', 'n_intervals'),
	Input('paused-store', 'data'),
	State('display-window-store', 'data'),
	State('pause-ref-store', 'data')
)
def update_graph(selected_fields, n, paused, display_minutes, pause_ref_iso):
	# remove epoch_ms from selected fields
	if not selected_fields:
		return go.Figure()
	selected_fields = [f for f in selected_fields if f != '_epoch_ms']
	data_points = fetch_data()
	# If paused and the interval triggered this callback, don't update the
	# Graph component — return no_update so the previously rendered figure
	# (and any user selection) remains intact. Allow updates when paused if
	# triggered by UI interactions (fields change or explicit pause toggle).
	trigger = None
	try:
		trig = dash.callback_context.triggered
		if trig:
			trigger = trig[0].get('prop_id')
	except Exception:
		trigger = None
	if paused and trigger and trigger.startswith('interval.'):
		return dash.no_update

	# Apply display-only time window if configured (do not modify MEMORY_POINTS)
	try:
		disp_minutes = float(display_minutes) if display_minutes is not None else 0
	except Exception:
		disp_minutes = 0
	# If paused with a captured reference timestamp, freeze the display to that moment
	ref_ts = None
	if paused and pause_ref_iso and data_points:
		try:
			ref_ts = datetime.datetime.strptime(pause_ref_iso, '%Y-%m-%d %H:%M:%S.%f')
		except Exception:
			ref_ts = None
		if ref_ts is not None:
			# show only points up to and including the paused reference
			data_points = [dp for dp in data_points if isinstance(dp.get('timestamp'), datetime.datetime) and dp['timestamp'] <= ref_ts]

	# If a display window is set, apply it relative to the appropriate reference
	if disp_minutes > 0 and data_points:
		# use pause ref if paused and available, else use latest timestamp
		if ref_ts is None:
			ref_ts_for_window = max((dp.get('timestamp') for dp in data_points if isinstance(dp.get('timestamp'), datetime.datetime)), default=None)
		else:
			ref_ts_for_window = ref_ts
		if ref_ts_for_window is not None:
			cutoff = ref_ts_for_window - datetime.timedelta(minutes=disp_minutes)
			data_points = [dp for dp in data_points if isinstance(dp.get('timestamp'), datetime.datetime) and dp['timestamp'] >= cutoff]
	if not data_points or not selected_fields:
		return go.Figure()
	timestamps = [dp['timestamp'] for dp in data_points]
	# Build hover customdata based on tooltip.json (fallback to timestamp + price)
	fields_for_tooltip = TOOLTIP_FIELDS or ['timestamp', 'price']
	customdata = []
	for dp in data_points:
		per_point_lines = []
		for idx, fname in enumerate(fields_for_tooltip):
			prefix = '' if idx == 0 else '<br>'
			if fname == 'timestamp':
				ts = dp.get('timestamp')
				if isinstance(ts, datetime.datetime):
					ts_str = ts.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
				else:
					ts_str = str(ts) if ts is not None else ''
				line = f"{prefix}<b>timestamp</b>: {html_escape(ts_str)}" if ts_str else ''
			else:
				val = dp.get(fname)
				if val is None or val == '':
					line = ''
				else:
					if fname == 'description':
						safe = html_escape(str(val))
						wrapped = textwrap.fill(safe, width=60).replace('\n', '<br>')
						line = f"{prefix}<b>description</b>: {wrapped}"
					else:
						line = f"{prefix}<b>{html_escape(fname)}</b>: {html_escape(str(val))}"
			per_point_lines.append(line)
		customdata.append(per_point_lines)
	# Compose a hovertemplate that renders only the configured fields
	hover_template = ''.join([f"%{{customdata[{i}]}}" for i in range(len(fields_for_tooltip))]) + "<extra></extra>"
	fig = go.Figure()
	for field in selected_fields:
		values = [dp.get(field) for dp in data_points]
		# Assign to secondary y-axis if configured
		yaxis_ref = 'y2' if AXES_MAP.get(field) == 'y2' else 'y'
		mode = MODES_MAP.get(field, 'lines')
		marker_cfg = MARKERS_MAP.get(field)
		line_cfg = LINES_MAP.get(field)
		trace_kwargs = dict(
			x=timestamps,
			y=values,
			mode=mode,
			name=field,
			yaxis=yaxis_ref,
			customdata=customdata,
			hovertemplate=hover_template,
		)
		if isinstance(marker_cfg, dict):
			trace_kwargs['marker'] = marker_cfg
		if isinstance(line_cfg, dict):
			trace_kwargs['line'] = line_cfg
		fig.add_trace(go.Scatter(**trace_kwargs))
	# Base layout: put legend at the bottom as a horizontal bar and reserve space
	fig.update_layout(
		xaxis_title=None,
		yaxis_title=None,
		legend_title=None,
		# place legend above the plot, centered
		legend=dict(orientation='h', y=1.02, yanchor='bottom', x=0.5, xanchor='center'),
		# increase top margin to accommodate legend and reduce bottom margin
		margin=dict(l=40, r=40, t=100, b=40),
		# ensure the plot background is clean (white) and gridlines are subtle
		paper_bgcolor='white',
		plot_bgcolor='white',
		xaxis=dict(showgrid=True, gridcolor='lightgray', zeroline=False, showline=False),
		yaxis=dict(showgrid=True, gridcolor='lightgray', zeroline=False, showline=False),
	)
	# Force hover popup to be white background with black text
	fig.update_layout(hoverlabel=dict(bgcolor='white', font=dict(color='black')))
	# Configure secondary y-axis if any selected field uses y2
	if any(AXES_MAP.get(f) == 'y2' for f in selected_fields):
		fig.update_layout(
			yaxis2=dict(title=None, overlaying='y', side='right', showgrid=False)
		)
	return fig


@app.callback(
	Output('clear-output', 'children'),
	Input('clear-button', 'n_clicks')
)
def clear_data(n_clicks):
	"""Clear in-memory stored points and seen keys when the button is clicked.

	Note: this clears only the in-process memory (MEMORY_POINTS and SEEN_KEYS).
	It does not delete keys from Redis. This keeps the web UI responsive and
	avoids destructive remote operations.
	"""
	if not n_clicks:
		return dash.no_update
	with MEM_LOCK:
		MEMORY_POINTS.clear()
		SEEN_KEYS.clear()
	return dash.no_update

if __name__ == "__main__":
	app.run(debug=True, port=8051)
