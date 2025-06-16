import React, { useState, useEffect, useRef } from 'react';

type ServiceState = 'playing' | 'paused' | 'out_of_hours' | 'manual_override';

type Song = {
  radio_title: string;
  radio_artist: string;
  album_art_url?: string;
  [key: string]: any;
};

type Stats = {
  top_artists: string;
  unique_artists: number;
  most_common_failure: string;
  success_rate: string;
  service_paused: boolean;
  paused_reason: string;
};

type StateHistoryEntry = {
  timestamp: string;
  state: string;
  reason: string;
};

const STATES: Record<ServiceState, { label: string; color: string }> = {
  playing: { label: 'Playing', color: 'bg-primary-light dark:bg-primary-dark' },
  paused: { label: 'Paused', color: 'bg-yellow-500' },
  out_of_hours: { label: 'Out of Hours', color: 'bg-gray-500' },
  manual_override: { label: 'Manual Override', color: 'bg-purple-700' },
};

const App: React.FC = () => {
  const [darkMode, setDarkMode] = useState(false);
  const [serviceState, setServiceState] = useState<ServiceState>('paused');
  const [manualOverride, setManualOverride] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [toastMsg, setToastMsg] = useState('');
  const [showHistory, setShowHistory] = useState(false);
  const [stateHistory, setStateHistory] = useState<StateHistoryEntry[]>([]);
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

  // Fetch status from backend
  const fetchStatus = async () => {
    try {
      const res = await fetch('/status');
      const data = await res.json();
      setServiceState(data.service_state);
      setStateHistory(data.state_history || []);
      setStats(data.stats || {});
      setDailyAdded(data.daily_added || []);
      setDailyFailed(data.daily_failed || []);
      setLastSong(data.last_song_added || null);
      setSecondsUntilNextCheck(data.seconds_until_next_check || 0);
      setManualOverride(data.service_state === 'manual_override');
    } catch (e) {
      triggerToast('Failed to fetch status from backend');
    }
  };

  // Initial and interval fetch
  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 60000);
    return () => clearInterval(interval);
  }, []);

  // Countdown timer
  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setSecondsUntilNextCheck((s) => (s > 0 ? s - 1 : 0));
    }, 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [secondsUntilNextCheck]);

  // Theme toggle
  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [darkMode]);

  // Toast helper
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

  // Schedule visualization
  const activeStart = 7.5; // 7:30
  const activeEnd = 22; // 22:00
  const now = new Date();
  const nowHour = now.getHours() + now.getMinutes() / 60;
  const percentStart = (activeStart / 24) * 100;
  const percentEnd = (activeEnd / 24) * 100;
  const percentNow = (nowHour / 24) * 100;

  // Timer display
  const min = Math.floor(secondsUntilNextCheck / 60);
  const sec = secondsUntilNextCheck % 60;

  return (
    <div className="min-h-screen flex flex-col items-center justify-start py-8 px-2 bg-background-light dark:bg-background-dark transition-colors">
      <div className="container mx-auto max-w-4xl bg-card-light dark:bg-card-dark rounded-xl shadow-lg p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="logo-x text-3xl font-bold tracking-widest select-none">RadioX</div>
          <button
            className="theme-switcher border px-4 py-1 rounded-full text-sm"
            onClick={() => setDarkMode((d) => !d)}
            aria-label="Toggle dark mode"
          >
            {darkMode ? 'Light Mode' : 'Dark Mode'}
          </button>
        </div>

        {/* State Indicator */}
        <div className="state-indicator mb-4">
          <span className={`state-dot ${STATES[serviceState].color}`}></span>
          <span className="state-label">{STATES[serviceState].label}</span>
          <button className="history-btn ml-3" onClick={() => setShowHistory(true)}>
            View State History
          </button>
        </div>

        {/* Controls */}
        <div className="controls mb-6">
          <button
            className="control-btn mr-2"
            disabled={!canPlay}
            title={canPlay ? 'Resume Service' : 'Cannot resume now'}
            onClick={() => adminAction('/admin/pause_resume')}
          >
            <span role="img" aria-label="Play">▶️</span>
          </button>
          <button
            className="control-btn"
            disabled={!canPause}
            title={canPause ? 'Pause Service' : 'Cannot pause now'}
            onClick={() => adminAction('/admin/pause_resume')}
          >
            <span role="img" aria-label="Pause">⏸️</span>
          </button>
          <div className="manual-override">
            <span className="text-sm">Manual Override</span>
            <div
              className={`manual-toggle ${manualOverride ? 'active' : ''}`}
              tabIndex={0}
              role="button"
              aria-pressed={manualOverride}
              onClick={() => adminAction('/admin/pause_resume')}
            >
              <div className="manual-toggle-knob"></div>
            </div>
          </div>
        </div>

        {/* Schedule Visualization */}
        <div className="schedule mb-6">
          <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400">
            <span>00:00</span>
            <span>Active: 07:30–22:00</span>
            <span>24:00</span>
          </div>
          <div className="schedule-bar relative mt-1">
            <div
              className="schedule-active absolute top-0 h-full rounded-lg"
              style={{ left: `${percentStart}%`, width: `${percentEnd - percentStart}%` }}
            ></div>
            <div
              className="absolute top-0 h-full border-l-2 border-primary-light dark:border-primary-dark"
              style={{ left: `${percentNow}%`, height: '100%' }}
            ></div>
          </div>
        </div>

        {/* Countdown Timer */}
        <div className="mb-6 text-center text-lg font-semibold text-primary-light dark:text-primary-dark">
          Next check in: {min}:{sec.toString().padStart(2, '0')}
        </div>

        {/* Last Song Added */}
        <div className="mb-6 flex items-center gap-4">
          <img
            src={lastSong?.album_art_url || 'https://placehold.co/64x64/2b2b2b/f1f1f1?text=?'}
            alt="Album Art"
            className="w-16 h-16 rounded"
          />
          <div>
            <div className="font-bold">Last Song Added:</div>
            <div className="text-lg">{lastSong ? `${lastSong.radio_title}` : 'No songs added yet today.'}</div>
            <div className="text-gray-500 dark:text-gray-400">{lastSong ? lastSong.radio_artist : ''}</div>
          </div>
        </div>

        {/* Stats & Analytics */}
        <div className="stats grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          <div className="card">
            <div className="font-semibold mb-2">Songs Added Today</div>
            <div className="text-3xl font-bold">{dailyAdded.length}</div>
            <div className="text-sm text-gray-500 dark:text-gray-400">Unique Artists: {stats.unique_artists}</div>
            <div className="text-sm text-gray-500 dark:text-gray-400">Top Artists: {stats.top_artists}</div>
          </div>
          <div className="card">
            <div className="font-semibold mb-2">Failures Today</div>
            <div className="text-3xl font-bold">{dailyFailed.length}</div>
            <div className="text-sm text-gray-500 dark:text-gray-400">Most Common Failure: {stats.most_common_failure}</div>
          </div>
        </div>

        {/* Songs Added Table */}
        <div className="card mb-6">
          <div className="font-semibold mb-2">Songs Added Today ({dailyAdded.length})</div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr>
                  <th className="px-2 py-1 text-left">Title</th>
                  <th className="px-2 py-1 text-left">Artist</th>
                </tr>
              </thead>
              <tbody>
                {dailyAdded.length > 0 ? (
                  dailyAdded.map((song, idx) => (
                    <tr key={idx} className="border-b border-border-light dark:border-border-dark">
                      <td className="px-2 py-1">{song.radio_title}</td>
                      <td className="px-2 py-1">{song.radio_artist}</td>
                    </tr>
                  ))
                ) : (
                  <tr><td colSpan={2}>No songs added yet today.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Failed Songs Table */}
        <div className="card mb-6">
          <div className="font-semibold mb-2">Songs That Failed Today ({dailyFailed.length})</div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr>
                  <th className="px-2 py-1 text-left">Title</th>
                  <th className="px-2 py-1 text-left">Artist</th>
                  <th className="px-2 py-1 text-left">Reason</th>
                </tr>
              </thead>
              <tbody>
                {dailyFailed.length > 0 ? (
                  dailyFailed.map((song, idx) => (
                    <tr key={idx} className="border-b border-border-light dark:border-border-dark">
                      <td className="px-2 py-1">{song.radio_title}</td>
                      <td className="px-2 py-1">{song.radio_artist}</td>
                      <td className="px-2 py-1">{song.reason}</td>
                    </tr>
                  ))
                ) : (
                  <tr><td colSpan={3}>No songs have failed today.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Admin Panel */}
        <div className="admin-panel">
          <div className="font-semibold mb-2">Admin Actions</div>
          <div className="admin-actions">
            <button className="admin-btn" onClick={() => adminAction('/admin/send_summary')}>Send Summary Email</button>
            <button className="admin-btn" onClick={() => adminAction('/admin/retry_failed')}>Retry Failed Songs</button>
            <button className="admin-btn" onClick={() => adminAction('/admin/force_duplicates')}>Check for Duplicates</button>
            <button className="admin-btn" onClick={() => adminAction('/admin/force_check')}>Force Check</button>
            <button className="admin-btn" onClick={() => adminAction('/admin/send_debug_log')}>Send Debug Log</button>
          </div>
        </div>
      </div>

      {/* Toast Notification */}
      <div className={`toast fixed z-50 left-1/2 bottom-10 px-6 py-3 rounded bg-gray-800 text-white text-center shadow-lg transition-all ${showToast ? 'show' : ''}`}>{toastMsg}</div>

      {/* State History Modal */}
      {showHistory && (
        <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-card-dark rounded-lg shadow-lg p-6 w-full max-w-md">
            <div className="flex justify-between items-center mb-4">
              <div className="font-bold text-lg">State Transition History</div>
              <button className="text-xl" onClick={() => setShowHistory(false)} aria-label="Close">×</button>
            </div>
            <ul className="space-y-2 max-h-64 overflow-y-auto">
              {stateHistory.map((entry, idx) => (
                <li key={idx} className="flex flex-col border-b border-border-light dark:border-border-dark pb-2">
                  <span className="text-xs text-gray-500 dark:text-gray-400">{entry.timestamp}</span>
                  <span className="font-semibold">{STATES[entry.state as ServiceState]?.label || entry.state}</span>
                  <span className="text-xs text-gray-400">{entry.reason}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
};

export default App;
