#!/usr/bin/env bash

set -e  # Exit on error

BIND_ADDR="0.0.0.0:${PORT:-10000}"
LOCKFILE="/tmp/moonuserbot.lock"
USERBOT_PID_FILE="/tmp/moonuserbot.pid"
GUNICORN_PID_FILE="/tmp/gunicorn.pid"
MONITOR_INTERVAL=30  # Check userbot health every 30 seconds

cat <<'EOF'
 _      ____  ____  _     
/ \__/|/  _ \/  _ \/ \  /|
| |\/||| / \|| / \|| |\ ||
| |  ||| \_/|| \_/|| | \||
\_/  \|\____/\____/\_/  \|
                          
Copyright (C) 2020-2025 by MoonTg-project@Github, < https://github.com/The-MoonTg-project >.
This file is part of < https://github.com/The-MoonTg-project/Moon-Userbot > project,
and is released under the "GNU v3.0 License Agreement".
Please see < https://github.com/The-MoonTg-project/Moon-Userbot/blob/main/LICENSE >
All rights reserved.
EOF

# Enhanced cleanup function with graceful Telegram disconnect
cleanup() {
    echo "🧹 Graceful shutdown initiated..."
    
    # Step 1: Stop userbot FIRST with graceful shutdown
    if [ -n "$USERBOT_PID" ] && kill -0 "$USERBOT_PID" 2>/dev/null; then
        echo "📱 Sending graceful shutdown signal to userbot (PID: $USERBOT_PID)..."
        kill -TERM "$USERBOT_PID" 2>/dev/null || true
        
        # Give userbot 15 seconds to gracefully disconnect from Telegram
        echo "⏳ Waiting for Telegram disconnect (15s timeout)..."
        for i in {1..15}; do
            if ! kill -0 "$USERBOT_PID" 2>/dev/null; then
                echo "✅ Userbot disconnected gracefully after ${i}s"
                break
            fi
            sleep 1
        done
        
        # Force kill if still running after timeout
        if kill -0 "$USERBOT_PID" 2>/dev/null; then
            echo "⚠️  Userbot didn't stop gracefully, force killing..."
            kill -9 "$USERBOT_PID" 2>/dev/null || true
            wait "$USERBOT_PID" 2>/dev/null || true
        fi
    fi
    
    # Step 2: Stop gunicorn
    if [ -n "$GUNICORN_PID" ] && kill -0 "$GUNICORN_PID" 2>/dev/null; then
        echo "🌐 Stopping web server (PID: $GUNICORN_PID)..."
        kill -TERM "$GUNICORN_PID" 2>/dev/null || true
        
        # Wait up to 5 seconds for gunicorn
        for i in {1..5}; do
            if ! kill -0 "$GUNICORN_PID" 2>/dev/null; then
                echo "✅ Web server stopped after ${i}s"
                break
            fi
            sleep 1
        done
        
        # Force kill if needed
        if kill -0 "$GUNICORN_PID" 2>/dev/null; then
            kill -9 "$GUNICORN_PID" 2>/dev/null || true
        fi
    fi
    
    # Step 3: Cleanup files
    rm -f "$LOCKFILE" "$USERBOT_PID_FILE" "$GUNICORN_PID_FILE"
    echo "✅ Shutdown complete"
}

trap cleanup EXIT INT TERM

# Check for existing instance
if [ -f "$LOCKFILE" ]; then
    OLD_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️  Another instance is running (PID: $OLD_PID). Stopping it..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 3
    fi
    rm -f "$LOCKFILE"
fi

# Create lock file
echo $$ > "$LOCKFILE"

echo "🚀 Starting Moon-Userbot..."

# Add startup delay to prevent race conditions with overlapping deployments
# This gives the old container time to disconnect from Telegram
if [ "$RENDER" = "true" ] || [ -n "$RENDER_SERVICE_ID" ]; then
    echo "☁️  Detected Render environment"
    echo "⏳ Applying 5-second startup delay to prevent deployment overlap..."
    sleep 5
    echo "✅ Startup delay complete"
fi

# Start userbot in background with logging
python main.py > /tmp/moonuserbot.log 2>&1 &
USERBOT_PID=$!
echo "$USERBOT_PID" > "$USERBOT_PID_FILE"

echo "📱 Userbot started (PID: $USERBOT_PID)"

# Wait for userbot to initialize (with timeout and health check)
echo "⏳ Waiting for userbot to initialize..."
MAX_WAIT=15
WAITED=0

while [ $WAITED -lt $MAX_WAIT ]; do
    if ! kill -0 "$USERBOT_PID" 2>/dev/null; then
        EXIT_CODE=$(wait "$USERBOT_PID" 2>/dev/null || echo $?)
        echo "❌ Userbot crashed during startup! Exit code: $EXIT_CODE"
        echo "📋 Last 50 lines of log:"
        tail -50 /tmp/moonuserbot.log
        
        if [ "$EXIT_CODE" = "2" ]; then
            echo ""
            echo "🚨 AUTH_KEY_DUPLICATED ERROR DETECTED!"
            echo "   This error occurs when another instance uses the same Telegram session."
            echo ""
            echo "💡 MOST LIKELY CAUSE:"
            echo "   During deployment, Render briefly runs TWO containers simultaneously."
            echo "   Both try to connect to Telegram → AUTH_KEY_DUPLICATED"
            echo ""
            echo "✅ SOLUTION APPLIED:"
            echo "   - Health check configured: /health/userbot"
            echo "   - Graceful shutdown: 15s disconnect window"
            echo "   - Startup delay: Prevents overlap"
            echo ""
            echo "🔄 NEXT STEPS:"
            echo "   This deployment will fail, but the NEXT one should succeed."
            echo "   The health check will prevent future overlaps."
            echo ""
            echo "⚠️  IF THIS PERSISTS:"
            echo "   1. Check Render dashboard for multiple running instances"
            echo "   2. Manually suspend service, wait 30s, then resume"
            echo "   3. Re-authenticate via dashboard if needed"
            exit 2
        elif [ "$EXIT_CODE" = "3" ]; then
            echo ""
            echo "🔒 ANOTHER INSTANCE IS ALREADY RUNNING!"
            echo "   A singleton lock prevents multiple instances."
            echo "   If this is an error, delete: /tmp/moonuserbot_instance.lock"
            exit 3
        fi
        exit 1
    fi
    
    sleep 1
    WAITED=$((WAITED + 1))
done

if kill -0 "$USERBOT_PID" 2>/dev/null; then
    echo "✅ Userbot initialized successfully!"
else
    echo "❌ Userbot initialization failed"
    echo "📋 Last 50 lines of userbot log:"
    tail -50 /tmp/moonuserbot.log 2>/dev/null || echo "No log file found"
    echo ""
    echo "🔍 Checking for common issues..."
    if grep -q "AUTH_KEY_DUPLICATED" /tmp/moonuserbot.log 2>/dev/null; then
        echo "⚠️  AUTH_KEY_DUPLICATED detected - deployment overlap still occurring"
    elif grep -q "DATABASE_URL" /tmp/moonuserbot.log 2>/dev/null; then
        echo "⚠️  Database connection issue detected"
    elif grep -q "STRINGSESSION" /tmp/moonuserbot.log 2>/dev/null; then
        echo "⚠️  Session string issue detected"
    else
        echo "⚠️  Unknown initialization failure - check logs above"
    fi
    exit 1
fi

# Start web server on PORT (required for Render) - WITHOUT exec to keep shell alive
echo "🌐 Starting web server on $BIND_ADDR..."

# AGGRESSIVE CLEANUP: Remove any old files that might be cached
echo "🧹 Removing any cached old files..."
cd /app || cd .
rm -f app_old.py app_old.pyc 2>/dev/null || true
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

# Debug: Show what Python files exist
echo "📂 Python files after cleanup:"
ls -la *.py 2>&1 | grep -E "app.*\.py" || echo "No app*.py files found"

# Verify app.py exists and is correct
if [ ! -f "app.py" ]; then
    echo "❌ ERROR: app.py not found!"
    exit 1
fi

echo "✅ app.py found, size: $(wc -c < app.py) bytes"
echo "First line: $(head -1 app.py)"
echo "Last line: $(tail -1 app.py)"
echo "---"
echo "First 50 lines of app.py:"
head -50 app.py
echo "---"

# Check what Python will actually import
echo "🐍 Testing what Python imports as 'app' module..."
python3 -c "
import sys
import app
print(f'  Module: {app.__file__}')
print(f'  Module size: {len(open(app.__file__).read())} bytes')
print(f'  Has Flask app attr: {hasattr(app, \"app\")}')
if hasattr(app, 'app'):
    rules = list(app.app.url_map._rules)
    print(f'  Number of routes: {len(rules)}')
    print(f'  First 5 routes: {[str(r) for r in rules[:5]]}')
else:
    print('  ERROR: No app attribute found!')
" 2>&1 || echo "  Import test failed!"

# Test Flask import
echo "🐍 Testing Flask import..."
python3 -c "from flask import Flask; print('  Flask imported successfully')" || exit 1

# Use python3 to start gunicorn with PYTHONPATH explicitly set
echo "🚀 Starting Gunicorn with explicit Python path..."
PYTHONPATH=/app:$PYTHONPATH python3 -m gunicorn app:app --bind "$BIND_ADDR" --workers 2 --timeout 120 --access-logfile - --error-logfile - &
GUNICORN_PID=$!
echo "$GUNICORN_PID" > "$GUNICORN_PID_FILE"
echo "🌐 Gunicorn started (PID: $GUNICORN_PID)"

# Monitor both processes and keep them alive
echo "👁️  Starting process monitor (checking every ${MONITOR_INTERVAL}s)..."

monitor_processes() {
    local userbot_restarts=0
    local max_restarts=3
    
    while true; do
        # Check userbot health
        if [ -f "$USERBOT_PID_FILE" ]; then
            SAVED_USERBOT_PID=$(cat "$USERBOT_PID_FILE")
            if ! kill -0 "$SAVED_USERBOT_PID" 2>/dev/null; then
                echo "⚠️  Userbot process (PID: $SAVED_USERBOT_PID) has stopped!"
                
                # Check exit code from log
                if grep -q "AUTH_KEY_DUPLICATED" /tmp/moonuserbot.log 2>/dev/null; then
                    echo "❌ AUTH_KEY_DUPLICATED detected - another instance is using this session"
                    echo "   The userbot cannot restart automatically. Please:"
                    echo "   1. Stop all other deployments"
                    echo "   2. Wait 60 seconds"
                    echo "   3. Restart this service"
                    # Don't restart on AUTH_KEY_DUPLICATED - it will keep failing
                    sleep infinity
                elif [ $userbot_restarts -lt $max_restarts ]; then
                    userbot_restarts=$((userbot_restarts + 1))
                    echo "🔄 Attempting to restart userbot (attempt $userbot_restarts/$max_restarts)..."
                    
                    # Clear the singleton lock if it exists
                    rm -f /tmp/moonuserbot_instance.lock
                    
                    # Restart userbot
                    python main.py > /tmp/moonuserbot.log 2>&1 &
                    USERBOT_PID=$!
                    echo "$USERBOT_PID" > "$USERBOT_PID_FILE"
                    echo "📱 Userbot restarted (PID: $USERBOT_PID)"
                    
                    # Wait to see if it stays alive
                    sleep 5
                    if kill -0 "$USERBOT_PID" 2>/dev/null; then
                        echo "✅ Userbot restart successful"
                        userbot_restarts=0  # Reset counter on success
                    else
                        echo "❌ Userbot restart failed"
                    fi
                else
                    echo "❌ Max restart attempts reached. Userbot will not auto-restart."
                    echo "📋 Last 30 lines of userbot log:"
                    tail -30 /tmp/moonuserbot.log
                fi
            fi
        fi
        
        # Check gunicorn health
        if [ -f "$GUNICORN_PID_FILE" ]; then
            SAVED_GUNICORN_PID=$(cat "$GUNICORN_PID_FILE")
            if ! kill -0 "$SAVED_GUNICORN_PID" 2>/dev/null; then
                echo "❌ Gunicorn process (PID: $SAVED_GUNICORN_PID) has stopped!"
                echo "   Exiting - the web server is required for the service to run."
                exit 1
            fi
        fi
        
        sleep "$MONITOR_INTERVAL"
    done
}

# Start monitor in background
monitor_processes &
MONITOR_PID=$!

# Wait for gunicorn (main process) - if it exits, everything should shut down
wait "$GUNICORN_PID"
