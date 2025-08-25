#!/bin/bash

# Redis status test script
set -e

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

print_status "Testing Redis connection..."

# Function to list Redis objects
list_redis_objects() {
    print_status "Current Redis objects:"
    
    # Get all keys
    keys=$(redis-cli keys "*" 2>/dev/null)
    
    if [ -z "$keys" ]; then
        print_info "No keys found in Redis database"
        return
    fi
    
    echo ""
    printf "%-30s %-10s %-20s\n" "KEY" "TYPE" "VALUE/SIZE"
    printf "%-30s %-10s %-20s\n" "---" "----" "----------"
    
    # Iterate through each key
    echo "$keys" | while IFS= read -r key; do
        if [ -n "$key" ]; then
            key_type=$(redis-cli type "$key" 2>/dev/null)
            
            case "$key_type" in
                "string")
                    value=$(redis-cli get "$key" 2>/dev/null | head -c 50)
                    if [ ${#value} -eq 50 ]; then
                        value="${value}..."
                    fi
                    printf "%-30s %-10s %-20s\n" "$key" "$key_type" "$value"
                    ;;
                "list")
                    length=$(redis-cli llen "$key" 2>/dev/null)
                    printf "%-30s %-10s %-20s\n" "$key" "$key_type" "length: $length"
                    ;;
                "set")
                    size=$(redis-cli scard "$key" 2>/dev/null)
                    printf "%-30s %-10s %-20s\n" "$key" "$key_type" "size: $size"
                    ;;
                "hash")
                    size=$(redis-cli hlen "$key" 2>/dev/null)
                    printf "%-30s %-10s %-20s\n" "$key" "$key_type" "fields: $size"
                    ;;
                "zset")
                    size=$(redis-cli zcard "$key" 2>/dev/null)
                    printf "%-30s %-10s %-20s\n" "$key" "$key_type" "members: $size"
                    ;;
                *)
                    printf "%-30s %-10s %-20s\n" "$key" "$key_type" "unknown"
                    ;;
            esac
        fi
    done
    
    echo ""
    total_keys=$(echo "$keys" | grep -c "." 2>/dev/null || echo "0")
    print_info "Total keys: $total_keys"
}

# Test Redis connection
if redis-cli ping &> /dev/null; then
    response=$(redis-cli ping 2>/dev/null)
    if [ "$response" = "PONG" ]; then
        print_success "Redis server is ON and responding"
        print_status "Redis is running on port 6379"
        
        # Show Redis info
        echo ""
        print_status "Redis server information:"
        redis-cli info server | grep -E "(redis_version|uptime_in_seconds|tcp_port)" 2>/dev/null || true
        
        echo ""
        # List current Redis objects
        list_redis_objects
    else
        print_warning "Redis server responded but with unexpected response: $response"
    fi
else
    print_error "Redis server is OFF or not responding"
    
    # Check if process exists but not responding
    if pgrep -x "redis-server" > /dev/null; then
        print_warning "Redis process exists but not responding to commands"
        print_status "You may need to restart Redis"
    else
        print_status "Redis process is not running"
        print_status "Use ./start_redis.sh to start Redis"
    fi
fi
