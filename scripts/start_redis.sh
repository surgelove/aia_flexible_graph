#!/bin/bash

# Redis startup script with error handling
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

# Check if Redis is installed
if ! command -v redis-server &> /dev/null; then
    print_error "Redis is not installed!"
    print_status "Please install Redis using: brew install redis"
    exit 1
fi

# Check if Redis is already running on the specified port
if pgrep -f "redis-server.*port $REDIS_PORT" > /dev/null; then
    print_warning "Redis server is already running on port $REDIS_PORT"
    print_status "Current Redis processes:"
    ps aux | grep "redis-server.*port $REDIS_PORT" | grep -v grep
    exit 0
fi

# Start Redis server
print_status "Starting Redis server on port $REDIS_PORT..."

# Start Redis server in background
redis-server --daemonize yes --port $REDIS_PORT 2>/dev/null

# Wait and verify it's running by testing connection
print_status "Waiting for Redis to start..."
for i in {1..10}; do
    if redis-cli -p $REDIS_PORT ping &> /dev/null; then
        response=$(redis-cli -p $REDIS_PORT ping 2>/dev/null)
        if [ "$response" = "PONG" ]; then
            print_status "Redis server started successfully on port $REDIS_PORT"
            print_status "Redis server is running and ready to accept connections"
            exit 0
        fi
    fi
    sleep 1
done

# If we get here, Redis didn't start properly
print_error "Redis server failed to start or is not responding"
exit 1
