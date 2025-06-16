# RadioX Spotify Playlist App

This app takes 'Now Playing' tracks from Radio X and adds them to a Spotify playlist automatically. It features a web UI for live status, manual controls, and daily email summaries.

## Versioning
- **Current Beta Version:** v7.0-beta
- See the changelog below for details on each beta release.

## Features
- Monitors Radio X for new tracks
- Adds tracks to a Spotify playlist
- Web UI for status and manual controls
- Persistent caching and duplicate prevention
- Daily email summaries
- Robust error handling and logging
- Improved state management with a single service_state model
- Admin state transition history endpoint for audit and debugging

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

## Frontend (React + Tailwind CSS)

A new modern frontend is now located in the `frontend/` directory. It uses React (with TypeScript) and Tailwind CSS for a responsive, modern UI with light/dark mode.

### Local Development
1. Go to the frontend directory:
   ```sh
   cd frontend
   ```
2. Install dependencies:
   ```sh
   npm install
   ```
3. Start the development server:
   ```sh
   npm start
   ```
   The app will be available at http://localhost:3000

### Production Build
1. Build the static files:
   ```sh
   npm run build
   ```
   This will output the production-ready files to `frontend/build/`.

2. To serve with Flask, copy the contents of `frontend/build/` to your Flask `static/` and `templates/` directories, or configure Flask to serve from `frontend/build` directly.

### Render Deployment
- On Render, add a build step for the frontend:
  ```sh
  cd frontend && npm install && npm run build
  ```
- Ensure Flask is configured to serve the built static files from `frontend/build`.

## 🚀 Deploying to Render (Web + Worker)

This app uses a two-process architecture for reliability:
- **Web Service**: Serves the Flask API and React frontend
- **Background Worker**: Runs the RadioXBot main loop (playlist checks)

### 1. Push your changes to GitHub

### 2. Deploy on Render
- Go to [Render.com](https://render.com/)
- Click "New +" → "Blueprint" and connect your repo
- Render will detect `render.yaml` and set up both services:
  - `radiox-spotify-web` (web service)
  - `radiox-spotify-bot-worker` (background worker)
- Both will share the same environment and dependencies

### 3. Confirm both services are running
- The web service should serve the dashboard and API
- The worker should log main loop activity (playlist checks)

### 4. Troubleshooting
- If the worker is not running, check its logs for errors
- Make sure both services are on the same branch (e.g., `beta`)

---

For local development, you can still run the Flask app and the bot loop separately:

```sh
# Terminal 1: Flask API (for frontend)
flask run

# Terminal 2: Main loop
python run_bot.py
```

## Changelog

### v7.0-beta
- **Major Backend Refactor:**
  - Replaced multiple state flags (`manual_override_active`, `override_paused`, etc.) with a single `service_state` variable for all play/pause/out-of-hours logic.
  - All backend logic, endpoints, and persistence now use `service_state` for clarity and maintainability.
  - Added a state transition history log, accessible via `/admin/state_history`, for admin review and debugging.
  - Cleaned up legacy code and improved reliability of state transitions.
- **API Changes:**
  - All status and admin endpoints now use the new state model.
  - Removed all references to the old flags in API responses and UI data.

### v6.3-beta (Previous)
- **State Persistence:**
  - `manual_override_active` and `override_paused` are now saved to and loaded from disk (`bot_state.json`) for robust cross-thread/process state sharing.
  - The main loop reloads state from disk at the start of every tick, ensuring admin actions are always respected immediately.
- **Debug Logging:**
  - Both the main loop and `toggle_pause_override` log process and thread IDs, as well as the state of `manual_override_active` and `override_paused` before and after changes.
- **Testing Improvements:**
  - Temporarily set `CHECK_INTERVAL` to 10 seconds for rapid testing, then restored to 120 seconds for production.
  - Confirmed that manual override now persists and the main loop runs as expected out of hours.
- **Reliability:**
  - Ensured that admin controls and main loop are robust and reliable, even after restarts or in multi-threaded environments.

### v6.2-beta
- **Manual Override System:**
  - Added `manual_override_active` flag to allow the service to run out of hours when manually resumed.
  - Manual override and pause state now reset at 07:00 each day (instead of 00:00).
  - Backend `/status` endpoint now returns both `override_paused` and `manual_override_active` for accurate UI state.
  - When "Resume Service" is clicked, the backend immediately triggers a track check (no need to wait for the next interval).
- **Logging & Diagnostics:**
  - Main loop now logs `should_run()`, `manual_override_active`, `override_paused`, and in-hours status every cycle for easier debugging.
  - Improved log clarity for admin actions and service state transitions.
- **UI/UX:**
  - (Planned/required) UI update to use new backend state for correct play/pause button logic and tooltips.
  - Button will show "Pause Service" if running (in hours or manual override), "Resume Service" if paused.
- **Bugfixes:**
  - Fixed issue where service would not run out of hours after manual resume.
  - Ensured all admin actions provide immediate feedback and update UI state.

### v6.1-beta
- **UI/UX:**
  - Play/Pause and Refresh icons now appear in the top-right of the status area for instant control.
  - Pause/Resume button shows a play icon and context-aware tooltip if paused (manual or out-of-hours).
  - If no songs have been added today, the status area now displays a message indicating if the service is paused (manual or out-of-hours).
  - Admin controls remain at the top, but the main controls are now more accessible and visually clear.
- **Feedback:**
  - Improved clarity on why the service is paused and what action the play/pause button will take.
  - Immediate feedback in the UI for all admin actions.

### v6.0-beta
- Major UI/UX and backend improvements: admin controls, timer, stats, email, and more (see previous changelog section for details).

## Notes
- Do not commit your `.env` or `app.log` files.
- For local development, use `python-dotenv` to load environment variables.

## Pushing Your Changes to GitHub
1. Make sure you are in your project directory:
   ```sh
   cd C:\Users\Tomlo\radiox-spotify-playlist-app
   ```
2. Stage your changes:
   ```sh
   git add .
   ```
3. Commit your changes with a message (update the version number as needed):
   ```sh
   git commit -m "v6.1-beta: UI/UX improvements, play/pause/refresh icons, context-aware pause messaging"
   ```
4. Push to GitHub:
   ```sh
   git push
   ```

## License
MIT 