# RadioX Spotify Playlist App

This app takes 'Now Playing' tracks from Radio X and adds them to a Spotify playlist automatically. It features a web UI for live status, manual controls, and daily email summaries.

## Features
- Monitors Radio X for new tracks
- Adds tracks to a Spotify playlist
- Web UI for status and manual controls
- Persistent caching and duplicate prevention
- Daily email summaries
- Robust error handling and logging

## Setup
1. Clone the repository:
   ```sh
   git clone --branch beta https://github.com/TomLomas/radiox-spotify-playlist-app.git
   cd radiox-spotify-playlist-app
   ```
2. Install dependencies:
   ```sh
   pip install -r requirements.txt
   ```
3. Create a `.env` file (see `.env` template) and fill in your credentials.
4. Run the app:
   ```sh
   python radiox_spotify.py
   ```

## Environment Variables
See `.env` for all required variables (Spotify, email, etc.).

## Deployment (Render)
- Add all environment variables in the Render dashboard.
- The `Procfile` is set up for web service deployment.
- Health check endpoint: `/health`

## Changelog: Major Additions, Removals, and Improvements

### Added
- **Admin Controls in Web UI:**
  - Refresh Status (immediate track check & timer reset)
  - Send Summary Email Now
  - Retry Failed Songs
  - Check for Duplicates
  - Pause/Resume Service (with auto-reset at new day)
- **Live Countdown Timer:** Shows time until next scheduled check, synced with backend.
- **Stats Section:** Top artists, unique artists, most common failure, and more, both in UI and `/status` API.
- **Mobile-Friendly Tables:** Song lists are scrollable and usable on mobile.
- **Toast Feedback:** All admin actions show a status message.
- **Cleaner, Modern Email Summary:** Redesigned for clarity and mobile use.
- **.env and app.log in .gitignore** for security.
- **/health endpoint** for deployment health checks.

### Improved
- **UI Simplification:** Removed confusing/unused manual triggers; focused on status, stats, and admin controls.
- **Accessibility:** Added ARIA labels and improved layout for screen readers.
- **Backend Security:** All secrets/configs now use environment variables and `python-dotenv`.
- **Error Handling:** More robust logging and error surfacing.
- **Summary Email Logic:** No more empty emails at midnight; only sends if there's something to report.
- **Code Documentation:** Added docstrings and comments throughout backend.

### Removed
- **Old Manual Trigger Buttons:** (force duplicates, force queue, diagnostics) from main UI.
- **Unnecessary UI Complexity:** Controls now grouped in a clear "Admin Controls" section.

## Notes
- Do not commit your `.env` or `app.log` files.
- For local development, use `python-dotenv` to load environment variables.

## License
MIT 