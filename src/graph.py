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

app.layout = html.Div([
	html.H2("Live Stock Data Graph"),
	dcc.Interval(id='interval', interval=100, n_intervals=0),
	dcc.Dropdown(id='fields-dropdown', multi=True, placeholder="Select fields to display"),
	dcc.Graph(id='live-graph'),
])

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
	Output('live-graph', 'figure'),
	Input('fields-dropdown', 'value'),
	Input('interval', 'n_intervals')
)
def update_graph(selected_fields, n):
	# remove epoch_ms from selected fields
	if not selected_fields:
		return go.Figure()
	selected_fields = [f for f in selected_fields if f != '_epoch_ms']
	data_points = fetch_data()
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
		mode = MODES_MAP.get(field, 'lines+markers')
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
	# Base layout
	fig.update_layout(xaxis_title='Timestamp', yaxis_title='Value', legend_title='Fields')
	# Force hover popup to be white background with black text
	fig.update_layout(hoverlabel=dict(bgcolor='white', font=dict(color='black')))
	# Configure secondary y-axis if any selected field uses y2
	if any(AXES_MAP.get(f) == 'y2' for f in selected_fields):
		fig.update_layout(
			yaxis2=dict(title='Value (y2)', overlaying='y', side='right', showgrid=False)
		)
	return fig

if __name__ == "__main__":
	app.run(debug=True, port=8051)
