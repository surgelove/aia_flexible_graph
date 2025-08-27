import json
import redis
import time
import uuid
from datetime import datetime
import subprocess
import threading
import pandas as pd
import pytz

class Redis_Utilities:
    """
    Utility class for interacting with Redis, including reading and writing JSON entries.
    """

    def __init__(self, host='localhost', port=6379, db=0, ttl=120):
        """
        Initialize the Redis_Utilities instance.

        Args:
            host (str): Redis server host.
            port (int): Redis server port.
            db (int): Redis database number.
            ttl (int): Time-to-live for written keys in seconds.
        """
        self.host = host
        self.port = port
        self.db = db
        self.ttl = ttl
        self.redis_db = redis.Redis(host=self.host, port=self.port, db=self.db)

    def read_all(self, prefix, order=True):
        """
        Read all Redis entries matching the given prefix, returning them as a sorted list of dicts.

        Args:
            prefix (str): Key prefix to scan for.
            order (bool): If True, sort results by 'timestamp'.

        Returns:
            list: List of dicts sorted by 'timestamp'.
        """
        seen = set()
        items = []
        for key in self.redis_db.scan_iter(f"{prefix}"):
            seen.add(key)
            raw = self.redis_db.get(key)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f" JSON decode error for key={key}: {e}")
            items.append(data)
        items.sort(key=lambda x: x["timestamp"])
        return items

    def read_each(self, prefix):
        """
        Continuously yield new Redis entries matching the given prefix as dicts.
        Prefix should be <prefix>:<instrument>

        Args:
            prefix (str): Key prefix to scan for.

        Yields:
            dict: Newly found Redis entry as a dict.
        """
        seen = set()
        while True:
            time.sleep(0.1)
            for key in self.redis_db.scan_iter(f"{prefix}:*"):
                if key not in seen:
                    seen.add(key)
                    raw = self.redis_db.get(key)
                    try:
                        data = json.loads(raw)
                        yield data
                    except json.JSONDecodeError as e:
                        print(f"JSON decode error for key={key}: {e}")
                        continue

    def write(self, prefix, value):
        """
        Write a dict value to Redis with a generated key using the given prefix.
        Prefix should be <prefix>:<instrument>

        Args:
            prefix (str): Key prefix for the entry.
            value (dict): Value to store as JSON.
        """
        assert isinstance(value, dict)
        self.redis_db.set(f"{prefix}:{uuid.uuid4().hex[:8]}", json.dumps(value), ex=self.ttl)

    def clear(self, prefix):
        """
        Delete all Redis keys matching the given prefix.
        Prefix should be <prefix>:<instrument>

        Args:
            prefix (str): Key prefix to scan for and delete.
        """
        for key in self.redis_db.scan_iter(f"{prefix}:*"):
            try:
                self.redis_db.delete(key)
            except Exception as e:
                print(f"Error deleting key={key}: {e}")

class TimeBasedMovement:

    def __init__(self, range):
        """Create a TimeBasedMovement tracker.

        Args:
            range (int): Window in minutes to calculate movement over.
        """
        # Holds dicts: {'timestamp': <pd.Timestamp>, 'price': <float>}
        self.data = []
        self.range = range
        # Keep a reasonable maximum to avoid unbounded memory growth
        self.max_size = 500

    def add(self, timestamp, price):
        self.data.append(
            {
                "timestamp": timestamp,
                "price": price,
            }
        )
        
        # Remove oldest data if queue exceeds max size
        if len(self.data) > self.max_size:
            self.data.pop(0)

    def clear(self):
        """Reset the stored price history to empty."""
        # Simple reset to drop all stored points
        self.data = []

    def calc(self):
        # Calculate the movement of the price for the last 5 minutes
        if len(self.data) < 2:
            return 0.0

        # Get the price data for the last n minutes
        range_ago = self.data[-1]["timestamp"] - pd.Timedelta(minutes=self.range)
        relevant_data = [d for d in self.data if d["timestamp"] > range_ago]

        if not relevant_data:
            return 0.0

        # Calculate the price movement percentage
        start_price = relevant_data[0]["price"]
        end_price = relevant_data[-1]["price"]
        
        # Avoid division by zero
        if start_price == 0:
            return 0.0
            
        return ((end_price - start_price) / start_price) * 100
    
def string_to_datetime(date_string):
    """
    Convert a string to a datetime object.

    Args:
        date_string (str): The date string to convert.

    Returns:
        datetime: The converted datetime object or None on error.
    """
    try:
        return datetime.fromisoformat(date_string.replace('Z', '+00:00'))
    except Exception as e:
        print(f"Error converting string to datetime: {e}")
        return None

def datetime_to_string(dt):
    """
    Convert a datetime object to an ISO-8601 string.

    Args:
        dt (datetime): The datetime object to convert.

    Returns:
        str: The converted ISO-8601 string or None on error.
    """
    try:
        return dt.isoformat()
    except Exception as e:
        print(f"Error converting datetime to string: {e}")
        return None
    

def say_nonblocking(text, voice=None, volume=2):
    """Speak `text` using the macOS `say` command without blocking.

    The speaking is performed in a daemon thread so the caller can
    continue execution immediately. Volume is set with `osascript`.

    Args:
        text (str): The text to speak.
        voice (str, optional): Voice name to pass to `say`.
        volume (int, optional): Volume level (0-100). Default 2 here
            matches the historical value in the repo; users can change it.
    """
    print("Speaking:", text)
    def speak():
        try:
            # Set system volume before speaking
            # This requires 'osascript' which is available on macOS
            volume_cmd = ['osascript', '-e', f'set volume output volume {volume}']
            subprocess.run(volume_cmd, check=True)
            
            # Now speak the text
            cmd = ['say']
            if voice:
                cmd.extend(['-v', voice])
            cmd.append(text)
            subprocess.run(cmd, check=True)
            
            # Optional: Reset volume to a default level when done
            # subprocess.run(['osascript', '-e', 'set volume output volume 75'], check=True)
        except Exception as e:
            print(f"Error with text-to-speech: {e}")
    
    # Run in a separate thread to avoid blocking
    thread = threading.Thread(target=speak, daemon=True)
    thread.start()


def convert_utc_to_ny(utc_time_str):
    """Convert an ISO-8601 UTC timestamp (optionally ending with 'Z')
    into a naive datetime string in the America/New_York timezone.

    Returns a string formatted as YYYY-MM-DD HH:MM:SS or None on error.
    """
    try:
        return (datetime.fromisoformat(utc_time_str.replace('Z', '+00:00'))
                .astimezone(pytz.timezone('America/New_York'))
                .replace(tzinfo=None, microsecond=0)
                .strftime('%Y-%m-%d %H:%M:%S'))
    except Exception as e:
        print(f"Error converting time: {e}")
        return None

def updown(direction):
    """Return a human-friendly direction label for a numeric delta.

    Args:
        direction (float): Positive for up, negative for down, zero for neutral.

    Returns:
        str or None: 'up', 'down', or None for no movement.
    """
    return "up" if direction > 0 else "down" if direction < 0 else None




