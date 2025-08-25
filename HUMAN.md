# Human notes

This application is part of Aia, our automated trading assistante decentralized system. Most of it was developed in a few hours using Github Copilot with GPT-5 Mini and Claude Sonnet 4. We do not request any help for now.

This application, running on ```localhost:app_port``` will display any number of instruments received from a redis stream running on ```redis_port``` with the pattern ```redis_key_pattern```, from the file ```config/main.json```

```json
config/main.json
{
  "redis_key_pattern": "price_data:*:*",
  "app_port": 8051,
  "redis_port": 6379
}
```

The flexible graph is able to display two y axes. By default, all fields discovered are displayed on axis y1. If you need a particular field to be on the second axis, configure it in the file ```config/axes.json```

```json
config/axes.json
{
    "spread_pips": "y2"
}
```

The flexible graph is able to display data as lines or markers, or both. By default it is ```lines```. To configure any field differently, add the field and its display mode in ```config/modes.json```

```json
config/modes.json
{
  "price": "lines+markers",
  "spread_pips": "markers",
  "ask": "lines",
  "bid": "lines"
}
```

The flexible graph can have its markers and lines configurable in ```config/lines.json``` and ```config/markers.json```. The entire configuration can be used, as specified in the plotly documentation.

```json
config/lines.json
{
  "price": {
    "width": 2,
    "dash": null,
    "color": "lightgray"
  },
  "spread_pips": {
    "width": 1,
    "dash": null,
    "color": "lightgray"
  },
  "ema_short": {
    "width": 0.5,
    "dash": null,
    "color": "blue"
  },
  "ema_long": {
    "width": 1,
    "dash": null,
    "color": "purple"
  }
}

config/markers.json
{
  "price": {
    "symbol": "square",
    "size": 10,
    "color": "rgba(255,0,0,0)",
    "line": {
      "color": "blue",
      "width": 2
    }
  }
}
```

The flexible graph will display a tooltip, for which you can select the fields it will display, in ```config/tooltip.json```.

```json
config/tooltip.json
{
    "fields": [
        "timestamp",
        "price",
        "description"
    ]
}
```

To start the application, navigate to the project root and type:

```
python3 src/main.py
```

Open a browser to the correct port on localhost

```
http://localhost:8051
```

Use the scripts to make sure redis is started, test it or stop it. It uses port 6379 by default but can be specified

```bash
./scripts/start_redis.sh 6379
./scripts/stop_redis.sh
./scripts/test_redis.sh
```

You can test the sending of data to the redis stream by running either 

```
python3 test/test_graph.py
``` 
and 

```
python3 test/test_graph_manual.py
```








