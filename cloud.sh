#!/usr/bin/env bash

BIND_ADDR="0.0.0.0:${PORT:-10000}"

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

echo "Starting Moon-Userbot..."

# Start userbot in background and run web server
python main.py &

# Wait a moment for userbot to initialize
sleep 5

# Start web server on PORT (required for Render)
echo "Starting web server on $BIND_ADDR..."
exec gunicorn app:app --bind "$BIND_ADDR" --workers 2 --timeout 120
