# Scout AI — Talent Triage System

AI-powered candidate triage PWA built on the Lazzaro Standard.

## Deploy to GitHub Pages

1. Create a new repo (e.g. `yourusername/scout`)
2. Upload all files from this folder
3. Go to **Settings → Pages → Source: Deploy from branch → main**
4. Your PWA will be live at `https://yourusername.github.io/scout/`

## Files

| File | Purpose |
|------|---------|
| `index.html` | Main PWA — entire app in one file |
| `manifest.json` | PWA install manifest |
| `sw.js` | Service worker (offline support) |
| `icons/` | App icons for all devices |
| `.nojekyll` | Required for GitHub Pages |

## Python Fetcher (Optional)

Download from inside the app → Settings → Downloads:

- `scout_fetcher.py` — Playwright Indeed bulk downloader
- `.env.example` → copy to `.env` and add credentials
- `requirements.txt` — pip install
- `start.bat` / `stop.bat` — Windows launchers

## Stack

- Frontend: Vanilla HTML/CSS/JS — zero build tools
- AI: Groq API (`llama-3.3-70b-versatile`)
- Storage: IndexedDB (local only)
- Python Bridge: Playwright

## Privacy

All candidate data stays in your browser's IndexedDB. Only the resume text you submit for AI analysis is sent to Groq's API. Use The Shredder to wipe everything.
