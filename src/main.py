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

# In-memory history to keep received data beyond Redis TTL per instrument
MEMORY_POINTS = {}  # dict[str, list[dict]] - keyed by instrument
SEEN_KEYS = set()   # set[str]
MEM_LOCK = Lock()
MAX_POINTS = 10000  # cap history to prevent unbounded growth per instrument

# Store to track current instruments and prevent unnecessary layout updates
CURRENT_INSTRUMENTS = set()

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
	keys = redis_client.keys("price_data:*:*")
	# Only fetch new keys to avoid re-adding duplicates
	new_keys = [k for k in keys if k not in SEEN_KEYS]
	for key in new_keys:
		raw = redis_client.get(key)
		if not raw:
			SEEN_KEYS.add(key)
			continue
		try:
			# Extract instrument from key: price_data:INSTRUMENT:timestamp
			key_parts = key.split(':')
			if len(key_parts) >= 3:
				instrument = key_parts[1]
			else:
				SEEN_KEYS.add(key)
				continue
			
			dp = json.loads(raw)
			# Parse timestamp: prefer ISO formats (with 'T' and optional timezone),
			# fall back to older space-separated formats.
			ts_raw = dp.get('timestamp')
			if isinstance(ts_raw, str):
				# try ISO first (handles '2025-08-25T11:52:32.755024' and offsets)
				try:
					dp['timestamp'] = datetime.datetime.fromisoformat(ts_raw)
				except Exception:
					try:
						dp['timestamp'] = datetime.datetime.strptime(ts_raw, '%Y-%m-%d %H:%M:%S.%f')
					except Exception:
						dp['timestamp'] = datetime.datetime.strptime(ts_raw, '%Y-%m-%d %H:%M:%S')
			else:
				# leave as-is (later checks will ignore non-datetime entries)
				pass
			# Extract numeric epoch from key suffix to use as a stable secondary sort key
			try:
				dp['_epoch_ms'] = int(key.rsplit(':', 1)[-1])
			except Exception:
				dp['_epoch_ms'] = 0
			with MEM_LOCK:
				if instrument not in MEMORY_POINTS:
					MEMORY_POINTS[instrument] = []
				MEMORY_POINTS[instrument].append(dp)
				SEEN_KEYS.add(key)
				# Trim if above cap (after sorting by timestamp + epoch)
				if len(MEMORY_POINTS[instrument]) > MAX_POINTS:
					MEMORY_POINTS[instrument].sort(key=lambda x: (x.get('timestamp'), x.get('_epoch_ms', 0)))
					del MEMORY_POINTS[instrument][:-MAX_POINTS]
		except Exception:
			SEEN_KEYS.add(key)
			continue
	# Return sorted snapshots of memory for all instruments
	with MEM_LOCK:
		result = {}
		for instrument, points in MEMORY_POINTS.items():
			result[instrument] = sorted(points, key=lambda x: (x.get('timestamp'), x.get('_epoch_ms', 0)))
		return result

def get_instruments():
	"""Get list of all instruments in alphabetical order"""
	fetch_data()  # Ensure data is loaded
	with MEM_LOCK:
		return sorted(MEMORY_POINTS.keys())

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

def create_instrument_section(instrument):
	"""Create a section for a single instrument with its own controls and graph"""
	
	return html.Div([
		# Header section for this instrument
		html.Div([
			html.H3(f"{instrument}", style={'margin': 0, 'fontSize': '18px', 'fontWeight': 'bold'}),
			# Display-window controls
			html.Div([
				html.Label('Show last (minutes):', style={'marginRight': '6px', 'fontSize': '12px'}),
				dcc.Input(id={'type': 'minutes-input', 'instrument': instrument}, type='number', min=0, value=0, placeholder='0 = all', style={'width': '100px'}),
				html.Button('Apply', id={'type': 'apply-button', 'instrument': instrument}, n_clicks=0, style={'marginLeft': '6px'}),
			], style={'display': 'flex', 'alignItems': 'center'}),
			# Hidden stores for this instrument
			dcc.Store(id={'type': 'display-store', 'instrument': instrument}, data=0),
			dcc.Store(id={'type': 'paused-store', 'instrument': instrument}, data=False),
			dcc.Store(id={'type': 'pause-ref-store', 'instrument': instrument}, data=None),
			# Hidden space toggle button
			html.Button(id={'type': 'space-toggle', 'instrument': instrument}, style={'display': 'none'}),
			# Visible pause/resume button
			html.Button('Pause', id={'type': 'pause-button', 'instrument': instrument}, n_clicks=0, style={'marginLeft': '8px'}),
			html.Button('Clear data', id={'type': 'clear-button', 'instrument': instrument}, n_clicks=0, style={'margin':'8px'}),
			html.Div(id={'type': 'clear-output', 'instrument': instrument}, style={'color': 'green', 'marginBottom': '8px'}),
			html.Div(id={'type': 'display-output', 'instrument': instrument}, style={'color': 'blue', 'marginBottom': '8px'}),
			html.Div(id={'type': 'pause-output', 'instrument': instrument}, style={'color': 'purple', 'marginBottom': '8px'}),
		], style={'padding': '8px', 'flex': '0 0 auto', 'display': 'flex', 'alignItems': 'center', 'gap': '12px', 'borderBottom': '1px solid #ddd'}),

		# Fields selector for this instrument
		html.Div([
			dcc.Dropdown(
				id={'type': 'fields-dropdown', 'instrument': instrument},
				multi=True,
				placeholder=f'Select fields for {instrument}',
				style={'width': '100%', 'fontSize': '12px'}
			),
		], style={'padding': '2px 2px', 'flex': '0 0 auto', 'width': '100%'}),

		# Graph for this instrument
		html.Div([
			dcc.Graph(id={'type': 'graph', 'instrument': instrument}, style={'height': '100%', 'width': '100%'}),
		], style={'flex': '1 1 auto', 'minHeight': 0, 'marginBottom': '0px', 'padding': '0px'}),

	], style={'height': '100vh', 'display': 'flex', 'flexDirection': 'column', 'marginBottom': '0'})

app = dash.Dash(__name__)

_FONT_STACK = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'

app.layout = html.Div([
	# Main header
	html.Div([
		html.H2("Flexible Graph - Multi Instrument", style={'margin': 0, 'fontSize': '20px', 'textAlign': 'center'}),
		dcc.Interval(id='interval', interval=500, n_intervals=0),
	], style={'padding': '12px', 'backgroundColor': '#f8f9fa', 'borderBottom': '2px solid #dee2e6'}),

	# Container for all instrument sections
	html.Div(id='instruments-container', children=[]),

], style={'fontFamily': _FONT_STACK, 'padding': '0', 'margin': '0', 'height': '100vh', 'display': 'flex', 'flexDirection': 'column'})

# Callback to dynamically create instrument sections
@app.callback(
	Output('instruments-container', 'children'),
	Input('interval', 'n_intervals')
)
def update_instruments_layout(n):
	global CURRENT_INSTRUMENTS
	instruments = get_instruments()
	new_instruments = set(instruments)
	
	# Only update layout if instruments have changed
	if new_instruments == CURRENT_INSTRUMENTS:
		return dash.no_update
	
	CURRENT_INSTRUMENTS = new_instruments
	
	if not instruments:
		return [html.Div("No instruments found. Waiting for data...", style={'textAlign': 'center', 'padding': '50px', 'fontSize': '16px', 'color': '#666'})]
	
	sections = []
	for instrument in instruments:
		section = create_instrument_section(instrument)
		sections.append(section)
	
	return sections

# Pattern-matching callbacks for dynamic instruments
@app.callback(
	Output({'type': 'fields-dropdown', 'instrument': dash.dependencies.MATCH}, 'options'),
	Output({'type': 'fields-dropdown', 'instrument': dash.dependencies.MATCH}, 'value'),
	Input('interval', 'n_intervals'),
	State({'type': 'fields-dropdown', 'instrument': dash.dependencies.MATCH}, 'value'),
	State({'type': 'fields-dropdown', 'instrument': dash.dependencies.MATCH}, 'id'),
)
def update_fields(n, current_value, component_id):
	instrument = component_id['instrument']
	all_data = fetch_data()
	data_points = all_data.get(instrument, [])
	fields = get_numeric_fields_union(data_points)
	fields = [f for f in fields if f != '_epoch_ms']
	options = [{'label': f, 'value': f} for f in fields]
	if current_value:
		new_value = [f for f in current_value if f in fields]
		return options, new_value
	return options, fields

@app.callback(
	Output({'type': 'display-store', 'instrument': dash.dependencies.MATCH}, 'data'),
	Input({'type': 'apply-button', 'instrument': dash.dependencies.MATCH}, 'n_clicks'),
	State({'type': 'minutes-input', 'instrument': dash.dependencies.MATCH}, 'value'),
)
def apply_display_window(n_clicks, minutes_value):
	if not n_clicks:
		return dash.no_update
	try:
		minutes = float(minutes_value) if minutes_value is not None else 0
	except Exception:
		return dash.no_update
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
	if not n_space_clicks and not n_visible_clicks:
		return dash.no_update, dash.no_update, dash.no_update

	instrument = component_id['instrument']
	new_paused = not bool(paused)
	ref_iso = None
	if new_paused:
		all_data = fetch_data()
		data_points = all_data.get(instrument, [])
		with MEM_LOCK:
			latest = None
			for dp in data_points:
				ts = dp.get('timestamp')
				if isinstance(ts, datetime.datetime):
					if latest is None or ts > latest:
						latest = ts
		if latest is not None:
			ref_iso = latest.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
		button_label = 'Resume'
	else:
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
	if not selected_fields:
		return go.Figure()
	
	instrument = component_id['instrument']
	selected_fields = [f for f in selected_fields if f != '_epoch_ms']
	all_data = fetch_data()
	data_points = all_data.get(instrument, [])
	
	# Check if paused and triggered by interval
	trigger = None
	try:
		trig = dash.callback_context.triggered
		if trig:
			trigger = trig[0].get('prop_id')
	except Exception:
		trigger = None
	if paused and trigger and trigger.startswith('interval.'):
		return dash.no_update

	# Apply time filtering
	try:
		disp_minutes = float(display_minutes) if display_minutes is not None else 0
	except Exception:
		disp_minutes = 0
	
	ref_ts = None
	if paused and pause_ref_iso and data_points:
		try:
			ref_ts = datetime.datetime.strptime(pause_ref_iso, '%Y-%m-%d %H:%M:%S.%f')
		except Exception:
			ref_ts = None
		if ref_ts is not None:
			data_points = [dp for dp in data_points if isinstance(dp.get('timestamp'), datetime.datetime) and dp['timestamp'] <= ref_ts]

	if disp_minutes > 0 and data_points:
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
	
	# Build hover customdata
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
	
	hover_template = ''.join([f"%{{customdata[{i}]}}" for i in range(len(fields_for_tooltip))]) + "<extra></extra>"
	fig = go.Figure()
	
	for field in selected_fields:
		values = [dp.get(field) for dp in data_points]
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
	
	fig.update_layout(
		title=f"{instrument}",
		xaxis_title=None,
		yaxis_title=None,
		legend_title=None,
		legend=dict(orientation='h', y=1.02, yanchor='bottom', x=0.5, xanchor='center'),
		margin=dict(l=40, r=40, t=60, b=40),
		paper_bgcolor='white',
		plot_bgcolor='white',
		xaxis=dict(showgrid=True, gridcolor='lightgray', zeroline=False, showline=False),
		yaxis=dict(showgrid=True, gridcolor='lightgray', zeroline=False, showline=False),
	)
	fig.update_layout(hoverlabel=dict(bgcolor='white', font=dict(color='black')))
	
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
	if not n_clicks:
		return dash.no_update
	instrument = component_id['instrument']
	with MEM_LOCK:
		if instrument in MEMORY_POINTS:
			del MEMORY_POINTS[instrument]
		# Remove keys for this instrument from SEEN_KEYS
		keys_to_remove = {k for k in SEEN_KEYS if k.startswith(f"price_data:{instrument}:")}
		SEEN_KEYS.difference_update(keys_to_remove)
	return dash.no_update

if __name__ == "__main__":
	app.run(debug=True, port=8051)
	app.run(debug=True, port=8051)
