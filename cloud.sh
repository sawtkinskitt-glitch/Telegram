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

# Cleanup function
cleanup() {
    echo "🧹 Cleaning up..."
    rm -f "$LOCKFILE" "$USERBOT_PID_FILE" "$GUNICORN_PID_FILE"
    
    if [ -n "$USERBOT_PID" ] && kill -0 "$USERBOT_PID" 2>/dev/null; then
        echo "Stopping userbot (PID: $USERBOT_PID)..."
        kill "$USERBOT_PID" 2>/dev/null || true
        wait "$USERBOT_PID" 2>/dev/null || true
    fi
    
    if [ -n "$GUNICORN_PID" ] && kill -0 "$GUNICORN_PID" 2>/dev/null; then
        echo "Stopping gunicorn (PID: $GUNICORN_PID)..."
        kill "$GUNICORN_PID" 2>/dev/null || true
        wait "$GUNICORN_PID" 2>/dev/null || true
    fi
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
            echo "   This means another instance is using the same session."
            echo "   Possible solutions:"
            echo "   1. Stop all other deployments/instances"
            echo "   2. Wait 30-60 seconds for Telegram to clear the session"
            echo "   3. Re-authenticate via the dashboard"
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
    exit 1
fi

# Start web server on PORT (required for Render) - WITHOUT exec to keep shell alive
echo "🌐 Starting web server on $BIND_ADDR..."
gunicorn app:app --bind "$BIND_ADDR" --workers 2 --timeout 120 --access-logfile - --error-logfile - &
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
