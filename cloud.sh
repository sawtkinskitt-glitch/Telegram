#!/usr/bin/env bash

set -e  # Exit on error

BIND_ADDR="0.0.0.0:${PORT:-10000}"
LOCKFILE="/tmp/moonuserbot.lock"
USERBOT_PID_FILE="/tmp/moonuserbot.pid"

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
    rm -f "$LOCKFILE" "$USERBOT_PID_FILE"
    if [ -n "$USERBOT_PID" ] && kill -0 "$USERBOT_PID" 2>/dev/null; then
        echo "Stopping userbot (PID: $USERBOT_PID)..."
        kill "$USERBOT_PID" 2>/dev/null || true
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

# Start web server on PORT (required for Render)
echo "🌐 Starting web server on $BIND_ADDR..."
exec gunicorn app:app --bind "$BIND_ADDR" --workers 2 --timeout 120 --access-logfile - --error-logfile -
