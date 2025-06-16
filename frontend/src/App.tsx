import React, { useState, useEffect, useRef, useCallback } from 'react';

// Type definitions
interface Song {
  radio_title: string;
  radio_artist: string;
  album_art_url?: string;
  reason?: string;
  [key: string]: any;
}
interface Stats {
  top_artists: string;
  unique_artists: number;
  most_common_failure: string;
  success_rate: string;
  service_paused: boolean;
  paused_reason: string;
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
  const [stats, setStats] = useState<Stats>({
    top_artists: '',
    unique_artists: 0,
    most_common_failure: '',
    success_rate: '',
    service_paused: false,
    paused_reason: '',
  });
  const [dailyAdded, setDailyAdded] = useState<Song[]>([]);
  const [dailyFailed, setDailyFailed] = useState<Song[]>([]);
  const [lastSong, setLastSong] = useState<Song | null>(null);
  const [secondsUntilNextCheck, setSecondsUntilNextCheck] = useState(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const lastFetchTime = useRef<number>(0);
  const isFetching = useRef<boolean>(false);
  const targetTimeRef = useRef<number>(Date.now() + secondsUntilNextCheck * 1000);
  const lastCheckTimeRef = useRef<number>(0);
  const checkCompleteRef = useRef<boolean>(true);

  // Fetch status from backend
  const fetchStatus = useCallback(async () => {
    if (isFetching.current) return;
    isFetching.current = true;

    try {
      const response = await fetch('/status');
      if (!response.ok) throw new Error('Failed to fetch status');
      const data = await response.json();
      
      // Update state with new data
      setServiceState(data.service_state);
      setStats(data.stats);
      setDailyAdded(data.daily_added);
      setDailyFailed(data.daily_failed);
      setLastSong(data.last_song_added || null);
      setManualOverride(data.service_state === 'manual_override');

      // Handle timer state
      if (data.is_checking) {
        // If a check is in progress, pause the timer
        setSecondsUntilNextCheck(0);
        checkCompleteRef.current = false;
      } else if (!checkCompleteRef.current && data.check_complete) {
        // If the check just completed, start a new timer
        checkCompleteRef.current = true;
        targetTimeRef.current = Date.now() + data.seconds_until_next_check * 1000;
        setSecondsUntilNextCheck(data.seconds_until_next_check);
      } else if (checkCompleteRef.current) {
        // If we're in a normal countdown, update the timer
        setSecondsUntilNextCheck(data.seconds_until_next_check);
      }

      lastFetchTime.current = Date.now();
    } catch (error) {
      console.error('Error fetching status:', error);
      triggerToast('Failed to fetch status');
    } finally {
      isFetching.current = false;
    }
  }, []);

  // Timer effect
  useEffect(() => {
    let isActive = true;

    const updateTimer = () => {
      if (!isActive) return;

      // Only update timer if we're not checking
      if (checkCompleteRef.current) {
        const now = Date.now();
        const remaining = Math.max(0, Math.floor((targetTimeRef.current - now) / 1000));

        setSecondsUntilNextCheck(remaining);

        // If we're at 0, trigger a fetch
        if (remaining === 0 && Date.now() - lastFetchTime.current >= 5000 && !isFetching.current) {
          fetchStatus();
        }
      }
    };

    // Initial fetch
    fetchStatus();

    // Set up interval for timer updates
    const intervalId = setInterval(updateTimer, 1000); // Update every second
    timerRef.current = intervalId;

    return () => {
      isActive = false;
      clearInterval(intervalId);
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
              <div className="text-gray-400">No songs added yet today.</div>
            )}
          </Card>

          {/* Songs Added Today Card */}
          <Card accent={accent}>
            <div className="font-bold text-lg mb-2">Songs Added Today</div>
            <div className="text-3xl font-extrabold mb-1" style={{ color: accent }}>{dailyAdded.length}</div>
            <div className="text-xs text-gray-500 mb-2">Unique Artists: {stats.unique_artists} | Top Artists: {stats.top_artists || 'N/A'}</div>
            <div className="overflow-y-auto max-h-24 w-full">
              {dailyAdded.length > 0 ? (
                <table className="w-full text-xs">
                  <thead><tr><th className="text-left">Title</th><th className="text-left">Artist</th><th className="text-left">Album Art</th></tr></thead>
                  <tbody>
                    {dailyAdded.map((song, i) => (
                      <tr key={i}>
                        <td>{song.radio_title}</td>
                        <td>{song.radio_artist}</td>
                        <td>{song.album_art_url ? <img src={song.album_art_url} alt="Album Art" className="w-8 h-8 rounded shadow" /> : null}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <div className="text-gray-400">No songs added yet today.</div>}
            </div>
          </Card>

          {/* Failures Today Card */}
          <Card accent={accent3}>
            <div className="font-bold text-lg mb-2">Failures Today</div>
            <div className="text-3xl font-extrabold mb-1" style={{ color: accent3 }}>{dailyFailed.length}</div>
            <div className="text-xs text-gray-500 mb-2">Most Common Failure: {stats.most_common_failure || 'N/A'}</div>
            <div className="overflow-y-auto max-h-24 w-full">
              {dailyFailed.length > 0 ? (
                <table className="w-full text-xs">
                  <thead><tr><th className="text-left">Title</th><th className="text-left">Artist</th><th className="text-left">Reason</th></tr></thead>
                  <tbody>
                    {dailyFailed.map((song, i) => (
                      <tr key={i}><td>{song.radio_title}</td><td>{song.radio_artist}</td><td>{song.reason || ''}</td></tr>
                    ))}
                  </tbody>
                </table>
              ) : <div className="text-gray-400">No songs have failed today.</div>}
            </div>
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

        {/* Toast Notification */}
        {showToast && (
          <div className="fixed bottom-6 left-1/2 transform -translate-x-1/2 bg-black bg-opacity-80 text-white px-6 py-3 rounded-lg shadow-lg z-50">
            {toastMsg}
          </div>
        )}
      </div>
    </div>
  );
};

export default App;
