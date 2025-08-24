import redis
import json
import time
import threading
import datetime
from dataclasses import dataclass
from typing import List
import random
import math

# Configurable send interval (seconds)
INTERVAL = 0.2

@dataclass
class DataPoint:
    timestamp: datetime.datetime
    price: float
    ema_short: float
    ema_long: float
    signal: str = None
    description: str = None

class StockDataGenerator:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.base_price = 150.50
        self.trend = 0.0001  # Slight upward trend
        self.volatility = 0.002
        self.ema_short_period = 12
        self.ema_long_period = 26
        self.ema_short = self.base_price
        self.ema_long = self.base_price
        self.last_signal = None
        
    def generate_price(self):
        """Generate realistic price movement"""
        random_walk = random.gauss(0, self.volatility)
        trend_component = self.trend
        
        # Add some mean reversion
        price_deviation = (self.base_price - self.ema_long) / self.base_price
        mean_reversion = -price_deviation * 0.001
        
        price_change = trend_component + random_walk + mean_reversion
        self.base_price *= (1 + price_change)
        
        return round(self.base_price, 4)
    
    def calculate_ema(self, price, current_ema, period):
        """Calculate Exponential Moving Average"""
        multiplier = 2 / (period + 1)
        return (price * multiplier) + (current_ema * (1 - multiplier))
    
    def detect_crossover(self, prev_short, prev_long, curr_short, curr_long):
        """Detect EMA crossover signals"""
        # Bullish crossover: short EMA crosses above long EMA
        if prev_short <= prev_long and curr_short > curr_long:
            return "BULLISH_CROSS"
        # Bearish crossover: short EMA crosses below long EMA
        elif prev_short >= prev_long and curr_short < curr_long:
            return "BEARISH_CROSS"
        return None
    
    def generate_data_point(self):
        """Generate a single data point with price and EMAs"""
        price = self.generate_price()
        
        # Store previous EMAs for crossover detection
        prev_ema_short = self.ema_short
        prev_ema_long = self.ema_long
        
        # Update EMAs
        self.ema_short = self.calculate_ema(price, self.ema_short, self.ema_short_period)
        self.ema_long = self.calculate_ema(price, self.ema_long, self.ema_long_period)
        
        # Detect crossover
        signal = self.detect_crossover(prev_ema_short, prev_ema_long, 
                                     self.ema_short, self.ema_long)
        
        # Generate description for signals
        description = None
        if signal == "BULLISH_CROSS":
            description = f"🟢 BULLISH SIGNAL: EMA-{self.ema_short_period} crossed above EMA-{self.ema_long_period}. Price: {price:.4f}, Short EMA: {self.ema_short:.4f}, Long EMA: {self.ema_long:.4f}"
        elif signal == "BEARISH_CROSS":
            description = f"🔴 BEARISH SIGNAL: EMA-{self.ema_short_period} crossed below EMA-{self.ema_long_period}. Price: {price:.4f}, Short EMA: {self.ema_short:.4f}, Long EMA: {self.ema_long:.4f}"
        
        return DataPoint(
            timestamp=datetime.datetime.now(),
            price=price,
            ema_short=round(self.ema_short, 4),
            ema_long=round(self.ema_long, 4),
            signal=signal,
            description=description
        )

class StockDataTester:
    def __init__(self, redis_host='localhost', redis_port=6379, redis_db=0):
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, db=redis_db, decode_responses=True)
        self.generator = StockDataGenerator(self.redis_client)
        self.running = False
        self.data_thread = None
        
    def test_connection(self):
        """Test Redis connection"""
        try:
            self.redis_client.ping()
            print("✅ Connected to Redis successfully")
            return True
        except redis.ConnectionError:
            print("❌ Failed to connect to Redis")
            return False
    
    def send_data_point(self, data_point: DataPoint):
        """Send a single data point to Redis"""
        try:
            # Create the data payload
            payload = {
                'timestamp': data_point.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],  # include milliseconds
                'price': data_point.price,
                'ema_short': data_point.ema_short,
                'ema_long': data_point.ema_long,
                'signal': data_point.signal,
                'description': data_point.description,
                'random_0_5': random.randint(0, 5)
            }
            # print(payload)
            
            # Use the same key pattern as your graph.py expects
            key = f"price_data:USD_JPY:{int(time.time() * 1000)}"
            
            # Send to Redis with TTL (5 seconds)
            self.redis_client.setex(key, 5, json.dumps(payload))
            
            print(f"📊 Sent: Price={data_point.price:.4f}, "
                  f"EMA-12={data_point.ema_short:.4f}, "
                  f"EMA-26={data_point.ema_long:.4f}")
            
            if data_point.signal:
                print(f"🚨 {data_point.signal}: {data_point.description}")
                
        except Exception as e:
            print(f"❌ Error sending data: {e}")
    
    def send_historical_data(self, num_points=50):
        """Send historical data points quickly to populate the graph"""
        print(f"📈 Sending {num_points} historical data points...")
        
        for i in range(num_points):
            # Create timestamps going back in time
            timestamp_offset = datetime.timedelta(seconds=(num_points - i) * INTERVAL)
            historical_time = datetime.datetime.now() - timestamp_offset
            
            data_point = self.generator.generate_data_point()
            data_point.timestamp = historical_time
            
            self.send_data_point(data_point)
            time.sleep(INTERVAL)  # Configurable delay to avoid overwhelming Redis
        
        print(f"✅ Historical data sent")
    
    def start_live_streaming(self, interval=None):
        """Start streaming live data"""
        if interval is None:
            interval = INTERVAL
        print(f"🔴 Starting live data stream (interval: {interval}s)")
        self.running = True
        
        def stream_data():
            while self.running:
                data_point = self.generator.generate_data_point()
                self.send_data_point(data_point)
                time.sleep(interval)
        
        self.data_thread = threading.Thread(target=stream_data, daemon=True)
        self.data_thread.start()
    
    def stop_streaming(self):
        """Stop the live data stream"""
        print("🛑 Stopping live data stream")
        self.running = False
        if self.data_thread:
            self.data_thread.join(timeout=5)
    
    def clear_redis_data(self):
        """Clear all test data from Redis"""
        try:
            keys = self.redis_client.keys("price_data:USD_JPY:*")
            if keys:
                self.redis_client.delete(*keys)
                print(f"🧹 Cleared {len(keys)} keys from Redis")
            else:
                print("🧹 No keys to clear")
        except Exception as e:
            print(f"❌ Error clearing Redis: {e}")

def run_comprehensive_test():
    """Run a comprehensive test of the graph system"""
    print("🚀 Starting Stock Data Graph Test")
    print("=" * 50)
    
    # Initialize tester
    tester = StockDataTester()
    
    # Test connection
    if not tester.test_connection():
        return
    
    try:
        # Clear any existing data
        tester.clear_redis_data()
        
        # Send historical data
        tester.send_historical_data(num_points=30)
        
        print("\n📱 Graph should now show historical data at http://localhost:8051")
        print("Press Enter to start live streaming...")
        input()
        
        # Start live streaming
        tester.start_live_streaming()
        
        print("\n✅ Live streaming started!")
        print("📊 Watch the graph update in real-time")
        print("🔍 Look for crossover signals (bullish/bearish)")
        print("Press Enter to stop...")
        input()
        
    except KeyboardInterrupt:
        print("\n⚠️ Test interrupted by user")
    finally:
        # Cleanup
        tester.stop_streaming()
        
        print("\nCleanup options:")
        print("1. Keep data for further testing")
        print("2. Clear all test data")
        choice = input("Choose (1/2): ").strip()
        
        if choice == "2":
            tester.clear_redis_data()
        
        print("✅ Test completed")

def run_signal_focused_test():
    """Run a test specifically designed to trigger crossover signals"""
    print("🎯 Running Signal-Focused Test")
    print("=" * 40)
    
    tester = StockDataTester()
    
    if not tester.test_connection():
        return
    
    # Clear existing data
    tester.clear_redis_data()
    
    # Manually create data points that will definitely trigger crossovers
    base_time = datetime.datetime.now()
    
    # Create scenario: price rises then falls to trigger both signals
    scenarios = [
        # Initial stable period
        (149.0, "Stable period"),
        (149.1, "Stable period"),
        (149.0, "Stable period"),
        # Price starts rising (will trigger bullish crossover)
        (149.5, "Price rising"),
        (150.0, "Price rising"),
        (150.8, "Price rising"),
        (151.5, "Price rising"),
        (152.2, "Price rising"),
        # Price starts falling (will trigger bearish crossover)
        (151.8, "Price falling"),
        (151.0, "Price falling"),
        (150.2, "Price falling"),
        (149.5, "Price falling"),
        (148.8, "Price falling"),
        (148.0, "Price falling"),
    ]
    
    print("📊 Sending scenario data to trigger crossovers...")
    
    for i, (price, description) in enumerate(scenarios):
        # Override the generator's price
        tester.generator.base_price = price
        data_point = tester.generator.generate_data_point()
        data_point.timestamp = base_time + datetime.timedelta(seconds=i * 5)
        
        tester.send_data_point(data_point)
        time.sleep(INTERVAL)
    
    print("✅ Scenario data sent")
    print("📱 Check the graph at http://localhost:8051")
    print("🔍 You should see bullish and bearish crossover signals!")

if __name__ == "__main__":
    print("Stock Data Graph Tester")
    print("======================")
    print("1. Comprehensive Test (historical + live streaming)")
    print("2. Signal-Focused Test (guaranteed crossovers)")
    print("3. Clear Redis Data")
    
    choice = input("Choose test type (1/2/3): ").strip()
    
    if choice == "1":
        run_comprehensive_test()
    elif choice == "2":
        run_signal_focused_test()
    elif choice == "3":
        tester = StockDataTester()
        if tester.test_connection():
            tester.clear_redis_data()
    else:
        print("Invalid choice")