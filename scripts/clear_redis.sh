#!/bin/bash

# Redis data clearing script with comprehensive cleanup
set -e

# Check if port argument is provided
if [ $# -ne 1 ]; then
    echo "Usage: $0 <port>"
    echo "Example: $0 6379"
    exit 1
fi

REDIS_PORT=$1

# Validate port number
if ! [[ "$REDIS_PORT" =~ ^[0-9]+$ ]] || [ "$REDIS_PORT" -lt 1024 ] || [ "$REDIS_PORT" -gt 65535 ]; then
    echo "Error: Port must be a number between 1024 and 65535"
    exit 1
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# Check if Redis CLI is installed
if ! command -v redis-cli &> /dev/null; then
    print_error "Redis CLI is not installed!"
    print_status "Please install Redis using: brew install redis"
    exit 1
fi

# Check if Redis is running on the specified port
if ! redis-cli -p $REDIS_PORT ping &> /dev/null; then
    print_error "Redis server is not running on port $REDIS_PORT"
    print_status "Please start Redis using: ./scripts/start_redis.sh $REDIS_PORT"
    exit 1
fi

print_status "Connected to Redis on port $REDIS_PORT"

# Count existing keys before clearing
total_keys=$(redis-cli -p $REDIS_PORT eval "return #redis.call('keys', '*')" 0 2>/dev/null || echo "0")
print_info "Found $total_keys keys in Redis database"

if [ "$total_keys" -eq 0 ]; then
    print_info "Redis database is already empty"
    exit 0
fi

# Show what will be cleared
print_status "Analyzing data to be cleared..."

# Count different types of data
price_data_keys=$(redis-cli -p $REDIS_PORT eval "return #redis.call('keys', 'price_data:*')" 0 2>/dev/null || echo "0")
stream_keys=$(redis-cli -p $REDIS_PORT eval "return #redis.call('keys', '*stream*')" 0 2>/dev/null || echo "0")
other_keys=$((total_keys - price_data_keys - stream_keys))

print_info "Price data keys: $price_data_keys"
print_info "Stream keys: $stream_keys"
print_info "Other keys: $other_keys"

# Confirm clearing
echo ""
print_warning "This will PERMANENTLY DELETE ALL DATA in Redis database on port $REDIS_PORT"
echo -n "Are you sure you want to continue? (y/N): "
read -r confirmation

if [[ ! "$confirmation" =~ ^[Yy]$ ]]; then
    print_status "Operation cancelled"
    exit 0
fi

print_status "Clearing Redis database..."

# Method 1: Use FLUSHDB to clear current database
print_status "Flushing current database..."
if redis-cli -p $REDIS_PORT flushdb &> /dev/null; then
    print_success "Successfully flushed current database"
else
    print_error "Failed to flush database, trying alternative method..."
    
    # Method 2: Delete keys by pattern if FLUSHDB fails
    print_status "Deleting keys by pattern..."
    
    # Delete price data keys
    if [ "$price_data_keys" -gt 0 ]; then
        print_status "Deleting price_data:* keys..."
        redis-cli -p $REDIS_PORT --scan --pattern "price_data:*" | xargs -r redis-cli -p $REDIS_PORT del &> /dev/null || true
    fi
    
    # Delete stream keys
    if [ "$stream_keys" -gt 0 ]; then
        print_status "Deleting stream keys..."
        redis-cli -p $REDIS_PORT --scan --pattern "*stream*" | xargs -r redis-cli -p $REDIS_PORT del &> /dev/null || true
    fi
    
    # Delete any remaining keys
    print_status "Deleting any remaining keys..."
    redis-cli -p $REDIS_PORT --scan --pattern "*" | xargs -r redis-cli -p $REDIS_PORT del &> /dev/null || true
fi

# Verify clearing
remaining_keys=$(redis-cli -p $REDIS_PORT eval "return #redis.call('keys', '*')" 0 2>/dev/null || echo "0")

if [ "$remaining_keys" -eq 0 ]; then
    print_success "Redis database completely cleared!"
    print_success "Deleted $total_keys keys"
else
    print_warning "Some keys may still remain: $remaining_keys keys"
    print_status "Showing remaining keys:"
    redis-cli -p $REDIS_PORT keys "*" 2>/dev/null || true
fi

print_status "Clear operation completed"
