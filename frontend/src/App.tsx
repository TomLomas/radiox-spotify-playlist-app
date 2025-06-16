import React, { useState } from 'react';

const STATES = {
  playing: { label: 'Playing', color: 'bg-primary-light dark:bg-primary-dark' },
  paused: { label: 'Paused', color: 'bg-yellow-500' },
  out_of_hours: { label: 'Out of Hours', color: 'bg-gray-500' },
  manual_override: { label: 'Manual Override', color: 'bg-purple-700' },
};

type ServiceState = keyof typeof STATES;

const App: React.FC = () => {
  // Placeholder state
  const [darkMode, setDarkMode] = useState(false);
  const [serviceState, setServiceState] = useState<ServiceState>('paused');
  const [manualOverride, setManualOverride] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [toastMsg, setToastMsg] = useState('');
  const [showHistory, setShowHistory] = useState(false);
  const [stateHistory] = useState([
    { timestamp: '2024-06-16 09:00', state: 'paused', reason: 'Startup' },
    { timestamp: '2024-06-16 09:05', state: 'playing', reason: 'In hours' },
    { timestamp: '2024-06-16 22:01', state: 'out_of_hours', reason: 'End of hours' },
  ]);

  // Placeholder stats
  const stats = {
    addedToday: 12,
    uniqueArtists: 8,
    topArtists: 'Artist A, Artist B',
    failedToday: 2,
    mostCommonFailure: 'Not found on Spotify',
  };

  // Placeholder schedule
  const activeStart = 7.5; // 7:30
  const activeEnd = 22; // 22:00
  const now = new Date();
  const nowHour = now.getHours() + now.getMinutes() / 60;
  const percentStart = (activeStart / 24) * 100;
  const percentEnd = (activeEnd / 24) * 100;
  const percentNow = (nowHour / 24) * 100;

  // Theme toggle
  React.useEffect(() => {
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
            onClick={() => {
              setServiceState('playing');
              triggerToast('Service resumed');
            }}
          >
            <span role="img" aria-label="Play">▶️</span>
          </button>
          <button
            className="control-btn"
            disabled={!canPause}
            title={canPause ? 'Pause Service' : 'Cannot pause now'}
            onClick={() => {
              setServiceState('paused');
              triggerToast('Service paused');
            }}
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
              onClick={() => {
                setManualOverride((m) => !m);
                setServiceState(manualOverride ? 'paused' : 'manual_override');
                triggerToast(manualOverride ? 'Manual override disabled' : 'Manual override enabled');
              }}
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

        {/* Stats & Analytics */}
        <div className="stats grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          <div className="card">
            <div className="font-semibold mb-2">Songs Added Today</div>
            <div className="text-3xl font-bold">{stats.addedToday}</div>
            <div className="text-sm text-gray-500 dark:text-gray-400">Unique Artists: {stats.uniqueArtists}</div>
            <div className="text-sm text-gray-500 dark:text-gray-400">Top Artists: {stats.topArtists}</div>
          </div>
          <div className="card">
            <div className="font-semibold mb-2">Failures Today</div>
            <div className="text-3xl font-bold">{stats.failedToday}</div>
            <div className="text-sm text-gray-500 dark:text-gray-400">Most Common Failure: {stats.mostCommonFailure}</div>
          </div>
        </div>

        {/* Admin Panel */}
        <div className="admin-panel">
          <div className="font-semibold mb-2">Admin Actions</div>
          <div className="admin-actions">
            <button className="admin-btn" onClick={() => triggerToast('Send summary email (not implemented)')}>Send Summary Email</button>
            <button className="admin-btn" onClick={() => triggerToast('Retry failed songs (not implemented)')}>Retry Failed Songs</button>
            <button className="admin-btn" onClick={() => triggerToast('Check for duplicates (not implemented)')}>Check for Duplicates</button>
            <button className="admin-btn" onClick={() => triggerToast('Force check (not implemented)')}>Force Check</button>
            <button className="admin-btn" onClick={() => triggerToast('Send debug log (not implemented)')}>Send Debug Log</button>
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
