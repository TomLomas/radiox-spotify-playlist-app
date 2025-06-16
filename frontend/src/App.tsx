import React, { useState, useEffect, useCallback } from 'react';

// Type definitions
interface Song {
  radio_title: string;
  radio_artist: string;
  album_art_url?: string;
  reason?: string;
  [key: string]: any;
}

// Accent color palettes
const PURPLES = ['#B266C8', '#a259c6', '#c77dff', '#7c3aed', '#a21caf', '#f472b6'];
const GREENS = ['#1DB954', '#22c55e', '#4ade80', '#16a34a', '#bbf7d0', '#166534'];

const XLogo: React.FC<{ darkMode: boolean }> = ({ darkMode }) => (
  <img
    src={darkMode ? '/x-purple.png' : '/x-green.png'}
    alt="RadioX Logo"
    className="w-16 h-16 mx-auto mb-2 drop-shadow-lg transition-all"
    style={{ filter: darkMode ? 'drop-shadow(0 0 8px #a259c6)' : 'drop-shadow(0 0 8px #22c55e)' }}
  />
);

const Card: React.FC<{ children: React.ReactNode; accent: string }> = ({ children, accent }) => (
  <div className="rounded-2xl shadow-lg p-6 bg-card-light dark:bg-card-dark flex flex-col items-center border-t-4" style={{ borderColor: accent }}>
    {children}
  </div>
);

const Button: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement> & { accent: string }> = ({ accent, children, ...props }) => (
  <button
    {...props}
    className={`px-4 py-2 rounded-lg font-semibold shadow transition-all focus:outline-none focus:ring-2 focus:ring-offset-2 mb-2 mx-1`}
    style={{ background: accent, color: '#fff', opacity: props.disabled ? 0.5 : 1 }}
  >
    {children}
  </button>
);

const App: React.FC = () => {
  const [darkMode, setDarkMode] = useState(true);
  const [serviceState, setServiceState] = useState('paused');
  const [manualOverride, setManualOverride] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [toastMsg, setToastMsg] = useState('');
  const [dailyAdded, setDailyAdded] = useState<Song[]>([]);
  const [dailyFailed, setDailyFailed] = useState<Song[]>([]);
  const [lastSong, setLastSong] = useState<Song | null>(null);
  const [lastCheckCompleteTime, setLastCheckCompleteTime] = useState<number>(0);
  const [secondsUntilNextCheck, setSecondsUntilNextCheck] = useState(0);
  const CHECK_INTERVAL = 120; // seconds

  // Timer effect: recalculate remaining time based on backend's last_check_complete_time
  useEffect(() => {
    if (!lastCheckCompleteTime) return;
    
    const updateTimer = () => {
      const now = Date.now() / 1000;
      const elapsed = now - lastCheckCompleteTime;
      const remaining = Math.max(0, Math.ceil(CHECK_INTERVAL - elapsed));
      setSecondsUntilNextCheck(remaining);
    };
    
    updateTimer();
    const intervalId = setInterval(updateTimer, 1000);
    return () => clearInterval(intervalId);
  }, [lastCheckCompleteTime]);

  // Fetch status from backend
  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch('/status');
      if (!response.ok) throw new Error('Failed to fetch status');
      const data = await response.json();
      setServiceState(data.service_state);
      setDailyAdded(data.daily_added);
      setDailyFailed(data.daily_failed);
      setLastSong(data.last_song_added || null);
      setManualOverride(data.service_state === 'manual_override');
      
      // Only update lastCheckCompleteTime if we get a valid timestamp
      if (data.last_check_complete_time && data.last_check_complete_time > 0) {
        console.log('Received check complete time:', new Date(data.last_check_complete_time * 1000).toLocaleString());
        setLastCheckCompleteTime(data.last_check_complete_time);
      }
    } catch (error) {
      console.error('Error fetching status:', error);
      triggerToast('Failed to fetch status');
    }
  }, []);

  // Fetch status every 30 seconds (30000ms)
  useEffect(() => {
    // Initial fetch
    fetchStatus();
    
    // Set up interval for subsequent fetches
    const fetchInterval = setInterval(fetchStatus, 30000);
    
    // Cleanup on unmount
    return () => {
      clearInterval(fetchInterval);
    };
  }, [fetchStatus]);

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [darkMode]);

  const triggerToast = (msg: string) => {
    setToastMsg(msg);
    setShowToast(true);
    setTimeout(() => setShowToast(false), 2500);
  };

  // Play/Pause logic
  const canPlay = serviceState === 'paused' || serviceState === 'out_of_hours';
  const canPause = serviceState === 'playing' || serviceState === 'manual_override';

  // Admin actions
  const adminAction = async (url: string, method: string = 'POST') => {
    try {
      const res = await fetch(url, { method });
      const text = await res.text();
      triggerToast(text);
      fetchStatus();
    } catch (e) {
      triggerToast('Admin action failed');
    }
  };

  // Accent color selection
  const accent = darkMode ? PURPLES[0] : GREENS[0];
  const accent2 = darkMode ? PURPLES[2] : GREENS[2];
  const accent3 = darkMode ? PURPLES[4] : GREENS[4];

  // Timer display
  const min = Math.floor(secondsUntilNextCheck / 60);
  const sec = secondsUntilNextCheck % 60;

  return (
    <div className={`min-h-screen w-full bg-background-light dark:bg-background-dark transition-colors duration-300`}>  
      <div className="max-w-5xl mx-auto py-8 px-2">
        {/* Header with X logo and theme toggle */}
        <div className="flex flex-col items-center mb-8">
          <XLogo darkMode={darkMode} />
          <div className="flex items-center justify-between w-full max-w-2xl">
            <h1 className="text-4xl font-extrabold tracking-widest" style={{ color: accent }}>RadioX</h1>
            <button
              className="border px-4 py-1 rounded-full text-sm font-semibold shadow"
              onClick={() => setDarkMode((d) => !d)}
              aria-label="Toggle dark mode"
              style={{ borderColor: accent, color: accent }}
            >
              {darkMode ? 'Light Mode' : 'Dark Mode'}
            </button>
          </div>
        </div>

        {/* Card grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
          {/* Service Status Card */}
          <Card accent={accent}>
            <div className="flex items-center gap-3 mb-2">
              <span className="inline-block w-3 h-3 rounded-full" style={{ background: accent2 }}></span>
              <span className="font-bold text-lg">{serviceState.charAt(0).toUpperCase() + serviceState.slice(1)}</span>
              <span className="ml-2 text-xs text-gray-400">{manualOverride ? 'Manual Override' : ''}</span>
            </div>
            <div className="flex gap-2 mb-2">
              <Button accent={accent2} disabled={!canPlay} onClick={() => adminAction('/admin/pause_resume')}>▶️ Play</Button>
              <Button accent={accent2} disabled={!canPause} onClick={() => adminAction('/admin/pause_resume')}>⏸ Pause</Button>
            </div>
            <div className="text-xs text-gray-500">Next check in: <span style={{ color: accent2 }}>{min}:{sec.toString().padStart(2, '0')}</span></div>
          </Card>

          {/* Last Song Added Card */}
          <Card accent={accent3}>
            <div className="font-bold text-lg mb-2">Last Song Added</div>
            {lastSong ? (
              <>
                <div className="font-semibold">{lastSong.radio_title}</div>
                <div className="text-sm text-gray-500">{lastSong.radio_artist}</div>
                {lastSong.album_art_url && <img src={lastSong.album_art_url} alt="Album Art" className="w-16 h-16 mt-2 rounded shadow" />}
              </>
            ) : (
              <div className="text-gray-500">No songs added yet</div>
            )}
          </Card>
        </div>

        {/* Admin Actions Card */}
        <Card accent={accent2}>
          <div className="font-bold text-lg mb-2">Admin Actions</div>
          <div className="flex flex-wrap gap-2 justify-center">
            <Button accent={accent2} onClick={() => adminAction('/admin/send_summary_email')}>Send Summary Email</Button>
            <Button accent={accent2} onClick={() => adminAction('/admin/retry_failed')}>Retry Failed Songs</Button>
            <Button accent={accent2} onClick={() => adminAction('/admin/check_duplicates')}>Check for Duplicates</Button>
            <Button accent={accent2} onClick={() => adminAction('/admin/force_check')}>Force Check</Button>
            <Button accent={accent2} onClick={() => adminAction('/admin/send_debug_log')}>Send Debug Log</Button>
          </div>
        </Card>

        {/* Daily Songs Grid */}
        <div className="mt-8">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Added Songs */}
            <Card accent={accent}>
              <div className="font-bold text-lg mb-4">Added Today</div>
              <div className="w-full">
                {dailyAdded.length > 0 ? (
                  dailyAdded.map((song, index) => (
                    <div key={index} className="flex items-center gap-3 mb-3 p-2 rounded-lg bg-gray-50 dark:bg-gray-800">
                      {song.album_art_url && (
                        <img src={song.album_art_url} alt="Album Art" className="w-12 h-12 rounded shadow" />
                      )}
                      <div>
                        <div className="font-semibold">{song.radio_title}</div>
                        <div className="text-sm text-gray-500">{song.radio_artist}</div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-gray-500">No songs added today</div>
                )}
              </div>
            </Card>

            {/* Failed Songs */}
            <Card accent={accent3}>
              <div className="font-bold text-lg mb-4">Failed Today</div>
              <div className="w-full">
                {dailyFailed.length > 0 ? (
                  dailyFailed.map((song, index) => (
                    <div key={index} className="flex items-center gap-3 mb-3 p-2 rounded-lg bg-gray-50 dark:bg-gray-800">
                      {song.album_art_url && (
                        <img src={song.album_art_url} alt="Album Art" className="w-12 h-12 rounded shadow" />
                      )}
                      <div>
                        <div className="font-semibold">{song.radio_title}</div>
                        <div className="text-sm text-gray-500">{song.radio_artist}</div>
                        {song.reason && (
                          <div className="text-xs text-red-500 mt-1">{song.reason}</div>
                        )}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-gray-500">No failures today</div>
                )}
              </div>
            </Card>
          </div>
        </div>
      </div>

      {/* Toast Notification */}
      {showToast && (
        <div className="fixed bottom-4 right-4 bg-gray-800 text-white px-4 py-2 rounded-lg shadow-lg">
          {toastMsg}
        </div>
      )}
    </div>
  );
};

export default App;
