#!/bin/bash

# Redis stop script with error handling
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
if ! command -v redis-cli &> /dev/null; then
    print_error "Redis CLI is not installed!"
    print_status "Please install Redis using: brew install redis"
    exit 1
fi

# Check if Redis is running
REDIS_PID=$(pgrep -f "redis-server" 2>/dev/null || echo "")
if [ -z "$REDIS_PID" ]; then
    print_warning "Redis server is not running"
    exit 0
fi

print_status "Found Redis server running with PID: $REDIS_PID"
print_status "Stopping Redis server..."

# Method 1: Try graceful shutdown via redis-cli
print_status "Attempting graceful shutdown..."
if timeout 5 redis-cli shutdown 2>/dev/null; then
    sleep 3
    if ! pgrep -f "redis-server" > /dev/null; then
        print_status "Redis server stopped gracefully"
        exit 0
    fi
fi

# Method 2: Try SIGTERM
print_warning "Graceful shutdown failed, sending SIGTERM..."
if kill -TERM "$REDIS_PID" 2>/dev/null; then
    sleep 3
    if ! pgrep -f "redis-server" > /dev/null; then
        print_status "Redis server stopped with SIGTERM"
        exit 0
    fi
fi

# Method 3: Force kill with SIGKILL
print_warning "SIGTERM failed, force killing Redis process..."
if kill -KILL "$REDIS_PID" 2>/dev/null; then
    sleep 2
    if ! pgrep -f "redis-server" > /dev/null; then
        print_status "Redis server forcefully stopped"
    else
        print_error "Failed to stop Redis server even with SIGKILL"
        exit 1
    fi
else
    print_error "Failed to kill Redis server process"
    exit 1
fi
            exit 1
        fi
    else
        print_error "Failed to kill Redis server process"
        exit 1
    fi
fi
