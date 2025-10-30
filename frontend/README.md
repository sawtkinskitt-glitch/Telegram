# Moon-Userbot Dashboard Frontend

This is the frontend for the Moon-Userbot Dashboard, deployed on Netlify.

## Configuration

- **Backend API:** https://moon-userbot-3aam.onrender.com
- **Frontend:** Hosted on Netlify

## API Endpoints

All API calls are made to the Render backend using the `apiCall()` helper function:

```javascript
const API_BASE_URL = 'https://moon-userbot-3aam.onrender.com';
```

## Local Development

To run locally:

1. Open `index.html` in a browser
2. The app will automatically connect to the Render backend
3. For local backend testing, change `API_BASE_URL` to `http://localhost:5000`

## Deployment

Deployed automatically to Netlify on every push to main branch.

## Features

- 📊 Real-time statistics and metrics
- 🤖 Command browser with categories
- 👤 Account management
- 🛡️ Ban risk monitoring
- 📈 Activity graphs and sparklines
- ⚡ FloodWait tracking
- 🎨 Apple-inspired design system
- ♿ WCAG 2.1 AA accessibility compliant

## Architecture

- **Frontend:** Static HTML/CSS/JavaScript (Netlify)
- **Backend:** Python Flask API (Render)
- **Database:** PostgreSQL (Render)
- **Communication:** REST API with CORS enabled
