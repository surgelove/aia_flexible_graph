import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import redis
import json
import time
import datetime
import random

# Redis connection
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

def fmt_ts(dt: datetime.datetime) -> str:
	return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

app = dash.Dash(__name__)

app.layout = html.Div([
	html.H3("Manual Stock Data Sender"),
	html.Div([
		html.Label("Timestamp (YYYY-MM-DD HH:MM:SS.mmm)"),
		dcc.Input(id='timestamp_input', type='text', value="", style={'width': '320px'}),
		html.Button('Use Now', id='set_now_btn', n_clicks=0, style={'marginLeft': '8px'}),
		html.Button('Now - 1 min', id='set_past_btn', n_clicks=0, style={'marginLeft': '6px'}),
	], style={'marginBottom': '8px'}),
	html.Div([
		html.Label("Price"),
		dcc.Input(id='price_input', type='number', value=None, step='any'),
		html.Label(" EMA Short", style={'marginLeft': '12px'}),
		dcc.Input(id='ema_short_input', type='number', value=None, step='any'),
		html.Label(" EMA Long", style={'marginLeft': '12px'}),
		dcc.Input(id='ema_long_input', type='number', value=None, step='any'),
	], style={'marginBottom': '8px'}),
	html.Div([
		html.Label("Signal"),
		dcc.Dropdown(id='signal_dropdown', options=[
			{'label': 'None', 'value': ''},
			{'label': 'BULLISH_CROSS', 'value': 'BULLISH_CROSS'},
			{'label': 'BEARISH_CROSS', 'value': 'BEARISH_CROSS'}
		], value=''),
	], style={'width': '260px', 'marginBottom': '8px'}),
	html.Div([
		html.Label("Description"),
		dcc.Textarea(id='description_input', value='', style={'width': '100%', 'height': '80px'})
	], style={'marginBottom': '8px', 'maxWidth': '640px'}),
	html.Div([
		html.Label("random_0_5"),
		dcc.Input(id='random_input', type='number', min=0, max=5, step=1, value=None),
		html.Button('Randomize', id='randomize_btn', n_clicks=0, style={'marginLeft': '8px'}),
		html.Label(" TTL (s)", style={'marginLeft': '12px'}),
		dcc.Input(id='ttl_input', type='number', min=1, step=1, value=2),
	], style={'marginBottom': '12px'}),
	html.Button('Submit', id='submit_btn', n_clicks=0, style={'fontWeight': 'bold'}),
	html.Div(id='status', style={'marginTop': '12px'})
])


@app.callback(
	Output('timestamp_input', 'value'),
	Output('random_input', 'value'),
	Input('set_now_btn', 'n_clicks'),
	Input('set_past_btn', 'n_clicks'),
	Input('randomize_btn', 'n_clicks'),
	State('timestamp_input', 'value'),
	State('random_input', 'value')
)
def handle_helpers(now_clicks, past_clicks, rand_clicks, ts_val, rnd_val):
	ctx = dash.callback_context
	if not ctx.triggered:
		return ts_val, rnd_val
	trig = ctx.triggered[0]['prop_id'].split('.')[0]
	if trig == 'set_now_btn':
		return fmt_ts(datetime.datetime.now()), rnd_val
	if trig == 'set_past_btn':
		return fmt_ts(datetime.datetime.now() - datetime.timedelta(minutes=1)), rnd_val
	if trig == 'randomize_btn':
		return ts_val, random.randint(0, 5)
	return ts_val, rnd_val


@app.callback(
	Output('status', 'children'),
	Input('submit_btn', 'n_clicks'),
	State('timestamp_input', 'value'),
	State('price_input', 'value'),
	State('ema_short_input', 'value'),
	State('ema_long_input', 'value'),
	State('signal_dropdown', 'value'),
	State('description_input', 'value'),
	State('random_input', 'value'),
	State('ttl_input', 'value')
)
def submit(n_clicks, ts_str, price, ema_s, ema_l, signal, description, rnd, ttl):
	if not n_clicks:
		return ''
	# Validate and defaults
	try:
		if ts_str:
			try:
				ts = datetime.datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S.%f')
			except ValueError:
				ts = datetime.datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
		else:
			ts = datetime.datetime.now()
		if price is None:
			return "❌ Price is required"
		ema_s = price if ema_s is None else float(ema_s)
		ema_l = price if ema_l is None else float(ema_l)
		rnd = random.randint(0, 5) if rnd is None else int(rnd)
		ttl = 2 if not ttl or ttl <= 0 else int(ttl)

		payload = {
			'timestamp': fmt_ts(ts),
			'price': float(price),
			'ema_short': ema_s,
			'ema_long': ema_l,
			'random_0_5': rnd,
		}

		# Only include optional fields when provided
		payload['signal'] = (signal or '') or None
		desc_clean = (description or '').strip()
		if desc_clean:
			payload['description'] = desc_clean

		key = f"price_data:USD_JPY:{int(time.time() * 1000)}"
		redis_client.setex(key, ttl, json.dumps(payload))
		return f"✅ Sent key={key} ts={payload['timestamp']} price={payload['price']} ttl={ttl}s"
	except Exception as e:
		return f"❌ Error: {e}"


if __name__ == '__main__':
	app.run(debug=True, port=8052)

