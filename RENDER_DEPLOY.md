# 🚀 Moon-Userbot - Render Deployment Guide

## One-Click Deploy to Render

Click the button below to deploy Moon-Userbot to Render with one click:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/sawtkinskitt-glitch/Telegram)

## What's Included

This deployment includes:
- 🤖 **Moon-Userbot** - Full-featured Telegram userbot
- 🌐 **Web Dashboard** - Account management interface
- 🔒 **Security Features** - Encrypted session storage
- 📊 **Safety Guardian** - Ban risk monitoring
- 💾 **SQLite Database** - Persistent storage (Render-compatible)

## Environment Variables

The deployment is pre-configured with the following environment variables:

### Required (Already Set)
- `API_ID` - Telegram API ID
- `API_HASH` - Telegram API Hash
- `STRINGSESSION` - Pyrogram session string
- `ACCOUNT_ENCRYPTION_KEY` - Encryption key for secure storage
- `DATABASE_TYPE` - Set to `sqlite3`
- `DATABASE_NAME` - Set to `db.sqlite3`
- `PM_LIMIT` - Anti-PM spam limit (default: 4)

### Optional (Can be added later)
- `APIFLASH_KEY` - For web screenshot plugin
- `RMBG_KEY` - For background removal plugin
- `VT_KEY` - For VirusTotal scanning
- `GEMINI_KEY` - For Gemini AI features
- `COHERE_KEY` - For Cohere AI features
- `SECOND_SESSION` - For music bot feature

## Post-Deployment

After deployment:

1. ✅ Your userbot will start automatically
2. 🌐 Web dashboard will be available at your Render URL
3. 📱 The bot will connect to Telegram with the provided session
4. 🔒 All account data is encrypted with AES-256-GCM

## Features

### Core Commands
- `.help` - Show all available commands
- `.ping` - Check bot responsiveness
- `.afk` - Set away from keyboard status
- `.clone` - Clone profile features
- And many more!

### Web Dashboard Features
- View all commands organized by category
- Monitor bot statistics
- Manage multiple accounts
- Track safety metrics and ban risk
- Generate new session strings
- Real-time health monitoring

## Architecture

```
┌─────────────────┐
│  Render Service │
│   (Web + Bot)   │
└────────┬────────┘
         │
    ┌────┴─────┐
    │          │
    ▼          ▼
┌─────────┐ ┌─────────────┐
│ Gunicorn│ │   Pyrogram  │
│  Flask  │ │  Userbot    │
│Dashboard│ │   Client    │
└────┬────┘ └──────┬──────┘
     │             │
     └──────┬──────┘
            │
     ┌──────▼───────┐
     │  SQLite DB   │
     │ (Persistent) │
     └──────────────┘
```

## Troubleshooting

### Service Not Starting
- Check Render logs for error messages
- Verify all environment variables are set correctly
- Ensure the `ACCOUNT_ENCRYPTION_KEY` is properly set

### Bot Not Responding
- Verify `STRINGSESSION` is valid
- Check `API_ID` and `API_HASH` are correct
- Review Telegram session status

### Web Dashboard 404
- Wait 2-3 minutes after deployment for services to fully start
- Check that the service type is set to "Web Service"
- Verify the PORT environment variable is being used

## Security Notes

⚠️ **Important Security Information**

- Your session string is encrypted using AES-256-GCM
- Never share your `ACCOUNT_ENCRYPTION_KEY` or `STRINGSESSION`
- The userbot has full access to your Telegram account
- Use at your own risk - see [DISCLAIMER](DISCLAIMER.md)

## Support

- 📢 [Official Channel](https://t.me/moonuserbot)
- 💬 [Support Chat](https://t.me/moonub_chat)
- 🧩 [Custom Modules](https://t.me/moonub_modules)
- 📖 [Documentation](https://github.com/The-MoonTg-project/Moon-Userbot/wiki)

## License

This project is licensed under the GNU General Public License v3.0 - see [LICENSE](LICENSE) for details.

---

**Made with ❤️ by [Moon-Userbot Team](https://github.com/The-MoonTg-project)**
