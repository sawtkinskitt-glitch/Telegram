# Moon-Userbot on Replit

## Overview
Moon-Userbot is a Telegram userbot built with Pyrogram/Pyrofork, providing AI-powered features and custom modules. It includes a Flask web interface for cloud deployment, multi-account management, AES-256-GCM encryption for session security, and an anti-ban protection system called SafetyGuardian. The project aims to offer a robust, secure, and extensible platform for Telegram automation with a focus on user experience and stability.

## User Preferences
- Database: SQLite3 (recommended for Replit)
- Deployment: Background Worker (no web server needed)
- Output: Console logs

## System Architecture
The project utilizes Pyrogram/Pyrofork for Telegram interaction and SQLite3 as the default database (with MongoDB also supported). It features a modular plugin system for extensibility and includes a background worker for 24/7 operation.

Key features and architectural decisions include:
- **Web Dashboard**: A minimal Flask web interface designed with an Apple 2025 aesthetic, running on port 5000.
- **Multi-Account Management**: Securely handles multiple Telegram accounts with AES-256-GCM encryption for session data. It includes a phone verification flow, profile synchronization, and real-time health monitoring for accounts.
- **SafetyGuardian Anti-Ban Protection**: Integrates a comprehensive system to prevent account bans, including rate limiting, FloodWait protection, ban risk scoring, and human-like delays. A dedicated UI panel displays rate limits, ban risk, and FloodWait countdowns.
- **Enhanced Clone Module**: A production-ready `.clone` command with advanced features such as:
    - **Reliability**: FloodWait auto-retry, pre-flight validation, post-clone verification, and atomic rollback.
    - **Advanced Features**: Preview mode, partial cloning (name, bio, photo, video, emoji, color), granular photo selection, profile video cloning, and multi-source combining.
    - **Preset System**: Save, load, list, and delete profile presets.
    - **History & Undo**: Browse and restore from profile change history, with a multi-level undo/redo stack.
    - **Performance & Polish**: Intelligent caching, lazy loading, optimized database queries, and enhanced error messages.
- **Project Structure**:
    - `main.py`: Main bot entry point.
    - `app.py`: Flask web server.
    - `cloud.sh`: Startup script.
    - `modules/`: Built-in bot modules.
    - `utils/`: Utility functions and configuration.
    - `string_gen.py`: Session string generator.

## External Dependencies
- **Telegram API**: Accessed via Pyrogram/Pyrofork.
- **PostgreSQL**: Supported for database storage (SQLite3 is default).
- **APIFLASH**: For web screenshot plugin (optional).
- **remove.bg**: For remove background plugin (optional).
- **VirusTotal**: For VirusTotal plugin (optional).
- **Gemini AI**: For Gemini AI plugin (optional).
- **Cohere AI**: For Cohere AI plugin (optional).