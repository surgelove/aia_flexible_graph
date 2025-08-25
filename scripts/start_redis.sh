#!/bin/bash

# Redis startup script with error handling
set -e

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

# Check if Redis is already running
if pgrep -f "redis-server" > /dev/null; then
    print_warning "Redis server is already running"
    print_status "Current Redis processes:"
    ps aux | grep redis-server | grep -v grep
    exit 0
fi

# Start Redis server
print_status "Starting Redis server..."

# Start Redis server in background
redis-server --daemonize yes --port 6379 2>/dev/null

# Wait and verify it's running by testing connection
print_status "Waiting for Redis to start..."
for i in {1..10}; do
    if redis-cli ping &> /dev/null; then
        response=$(redis-cli ping 2>/dev/null)
        if [ "$response" = "PONG" ]; then
            print_status "Redis server started successfully on port 6379"
            print_status "Redis server is running and ready to accept connections"
            exit 0
        fi
    fi
    sleep 1
done

# If we get here, Redis didn't start properly
print_error "Redis server failed to start or is not responding"
exit 1
