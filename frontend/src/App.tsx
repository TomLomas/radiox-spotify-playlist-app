import React, { useState, useEffect, useRef } from 'react';
import { BrowserRouter as Router, Routes, Route, useNavigate } from 'react-router-dom';
import AdminPage from './AdminPage';
import { Song, AdminStats } from './types';

// UI Components
const Button: React.FC<{ onClick?: () => void; accent: string; children: React.ReactNode; type?: 'button' | 'submit' | 'reset'; disabled?: boolean; className?: string }> = ({ onClick, accent, children, type = 'button', disabled, className }) => (
  <button
    onClick={onClick}
    type={type}
    className={`px-4 py-2 rounded-lg border transition-colors ${className || ''}`}
    style={{ borderColor: accent, color: accent }}
    disabled={disabled}
  >
    {children}
  </button>
);

const Card: React.FC<{ className?: string; children: React.ReactNode }> = ({ className = '', children }) => (
  <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-lg ${className}`}>
    {children}
  </div>
);

const CHECK_INTERVAL = 120; // seconds

const App: React.FC = () => {
  const [theme, setTheme] = useState<'light' | 'dark'>('dark');
  const [status, setStatus] = useState<any>(null);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [dailyAdded, setDailyAdded] = useState<Song[]>([]);
  const [isPlaying, setIsPlaying] = useState(true);
  const [timer, setTimer] = useState(CHECK_INTERVAL);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const accent = theme === 'dark' ? '#9333ea' : '#22c55e';
  const [lastCheckComplete, setLastCheckComplete] = useState<string | null>(null);
  const [nextCheckTime, setNextCheckTime] = useState<string | null>(null);
  const navigate = useNavigate();

  // Dark mode: toggle class on <body>
  useEffect(() => {
    document.body.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  // Fetch status and stats
  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statusRes, statsRes] = await Promise.all([
          fetch('/status'),
          fetch('/admin/stats')
        ]);
        const statusData = await statusRes.json();
        const statsData = await statsRes.json();
        setStatus(statusData);
        setStats(statsData.stats);
        setDailyAdded(statusData.daily_added || []);
        setLastCheckComplete(statusData.last_check_complete_time || null);
        setNextCheckTime(statusData.next_check_time || null);
      } catch (error) {
        console.error('Error fetching data:', error);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  // Timer logic: only reset when lastCheckComplete changes
  useEffect(() => {
    if (!isPlaying) return;
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      if (nextCheckTime) {
        const now = new Date();
        const next = new Date(nextCheckTime);
        const diff = Math.max(0, Math.floor((next.getTime() - now.getTime()) / 1000));
        setTimer(diff);
      }
    }, 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isPlaying, nextCheckTime]);

  // Reset timer only when lastCheckComplete changes
  useEffect(() => {
    if (lastCheckComplete && nextCheckTime) {
      const now = new Date();
      const next = new Date(nextCheckTime);
      const diff = Math.max(0, Math.floor((next.getTime() - now.getTime()) / 1000));
      setTimer(diff);
    }
  }, [lastCheckComplete, nextCheckTime]);

  const toggleTheme = () => {
    setTheme(theme === 'dark' ? 'light' : 'dark');
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col items-center px-4 py-8 gap-8">
      {/* Logo and Topbar */}
      <div className="w-full max-w-5xl flex flex-col md:flex-row items-center justify-between mb-8 gap-4">
        <div className="flex items-center gap-4">
          <img src="/x-purple.png" alt="Radio X" className="w-20 h-20 drop-shadow-lg" />
          <span className="text-3xl font-bold tracking-tight">Radio X Spotify Playlist</span>
        </div>
        <div className="flex gap-4">
          <Button onClick={toggleTheme} accent={accent}>
            {theme === 'dark' ? '🌞' : '🌙'}
          </Button>
          <Button onClick={() => navigate('/admin')} accent={accent}>
            <span className="inline-flex items-center gap-2"><span className="material-icons">settings</span> Admin Controls</span>
          </Button>
        </div>
      </div>

      {/* Main Grid */}
      <div className="w-full max-w-5xl grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* Playing Card */}
        <Card className="flex flex-col items-center justify-center p-8 gap-4 shadow-xl">
          <div className="flex items-center gap-2 w-full justify-between mb-2">
            <h2 className="text-2xl font-bold">Playing</h2>
            {status?.service_state && (
              <span className={`px-3 py-1 rounded-full text-xs font-bold ${
                status.service_state === 'playing' ? 'bg-green-100 text-green-700' :
                status.service_state === 'paused' ? 'bg-yellow-100 text-yellow-700' :
                'bg-gray-200 text-gray-700'
              }`}>
                {status.service_state === 'playing' && 'Active'}
                {status.service_state === 'paused' && 'Paused'}
                {status.service_state === 'out_of_hours' && 'Out of Hours'}
                {status.service_state !== 'playing' && status.service_state !== 'paused' && status.service_state !== 'out_of_hours' && status.service_state}
              </span>
            )}
          </div>
          <div className="flex items-center gap-4">
            <Button
              onClick={async () => { await fetch('/admin/resume', { method: 'POST' }); setIsPlaying(true); }}
              accent={accent}
              disabled={isPlaying}
            >
              ▶️ Play
            </Button>
            <Button
              onClick={async () => { await fetch('/admin/pause', { method: 'POST' }); setIsPlaying(false); }}
              accent={accent}
              disabled={!isPlaying}
            >
              ⏸ Pause
            </Button>
            <span className="text-lg font-mono bg-gray-100 dark:bg-gray-900 px-3 py-1 rounded">
              {formatTime(timer)}
            </span>
          </div>
        </Card>
        {/* Last Song Added Card */}
        <Card className="flex flex-col items-center justify-center p-8 gap-4 shadow-xl">
          <h2 className="text-2xl font-bold mb-2">Last Song Added</h2>
          {status?.last_song_added ? (
            <div className="flex items-center gap-4">
              {status.last_song_added.album_art_url && (
                <img src={status.last_song_added.album_art_url} alt="Album Art" className="w-16 h-16 rounded shadow" />
              )}
              <div>
                <p className="text-lg font-semibold">{status.last_song_added.radio_title}</p>
                <p className="text-sm text-muted-foreground">{status.last_song_added.radio_artist}</p>
              </div>
            </div>
          ) : (
            <p className="text-muted-foreground">No songs added yet</p>
          )}
        </Card>
      </div>

      {/* Statistics Card */}
      <div className="w-full max-w-5xl">
        <Card className="p-8 shadow-xl">
          <h2 className="text-2xl font-bold mb-6 flex items-center gap-2"><span className="material-icons">insights</span> Statistics</h2>
          {/* Performance Stats */}
          <div className="mb-6">
            <h3 className="text-lg font-semibold mb-2">Performance Stats</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-4">
              <div>
                <p className="text-sm text-muted-foreground">Total Songs Added</p>
                <p className="text-lg font-bold">{typeof stats?.total_songs_added === 'number' ? stats.total_songs_added : 'N/A'}</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Total Failures</p>
                <p className="text-lg font-bold">{typeof stats?.total_failures === 'number' ? stats.total_failures : 'N/A'}</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Success Rate</p>
                <p className="text-lg font-bold">{typeof stats?.success_rate === 'number' ? `${stats.success_rate}%` : 'N/A'}</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Avg Songs/Day</p>
                <p className="text-lg font-bold">{typeof stats?.average_songs_per_day === 'number' ? stats.average_songs_per_day : 'N/A'}</p>
              </div>
            </div>
          </div>
          <hr className="my-6 border-t border-gray-300 dark:border-gray-700" />
          {/* Song Insights */}
          <div className="mb-6">
            <h3 className="text-lg font-semibold mb-2">Song Insights</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-4">
              <div>
                <p className="text-sm text-muted-foreground">Average Duration</p>
                <p className="text-lg font-bold">
                  {stats?.average_duration 
                    ? `${Math.floor(stats.average_duration / 60)}:${String(Math.round(stats.average_duration % 60)).padStart(2, '0')}`
                    : 'N/A'}
                </p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Decade Spread</p>
                <p className="text-lg font-bold">
                  {stats?.decade_spread 
                    ? Object.entries(stats.decade_spread)
                        .map(([decade, percent]) => `${decade}: ${percent}%`)
                        .join(', ')
                    : 'N/A'}
                </p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Newest Song</p>
                <p className="text-lg font-bold">
                  {stats?.newest_song 
                    ? `${stats.newest_song.radio_title} (${stats.newest_song.year})`
                    : 'N/A'}
                </p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Oldest Song</p>
                <p className="text-lg font-bold">
                  {stats?.oldest_song 
                    ? `${stats.oldest_song.radio_title} (${stats.oldest_song.year})`
                    : 'N/A'}
                </p>
              </div>
            </div>
          </div>
          <hr className="my-6 border-t border-gray-300 dark:border-gray-700" />
          {/* Service Status */}
          <div>
            <h3 className="text-lg font-semibold mb-2">Service Status</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <p className="text-sm text-muted-foreground">Last Check</p>
                <p className="text-lg font-bold">{lastCheckComplete ? new Date(lastCheckComplete).toLocaleString() : 'N/A'}</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Next Check</p>
                <p className="text-lg font-bold">{nextCheckTime ? new Date(nextCheckTime).toLocaleString() : 'N/A'}</p>
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* Added Today */}
      <div className="w-full max-w-5xl">
        <Card className="p-8 shadow-xl">
          <h2 className="text-2xl font-bold mb-6 flex items-center gap-2"><span className="material-icons">library_music</span> Added Today</h2>
          <div>
            {dailyAdded.length > 0 ? (
              <ul className="space-y-4">
                {dailyAdded.map((song, index) => (
                  <li key={index} className="flex items-center gap-4 p-2 rounded hover:bg-gray-50 dark:hover:bg-gray-900 transition">
                    {song.album_art_url && (
                      <img src={song.album_art_url} alt="Album Art" className="w-12 h-12 rounded shadow" />
                    )}
                    <div>
                      <span className="font-semibold text-lg">{song.radio_title}</span>
                      <span className="ml-2 text-muted-foreground">{song.radio_artist}</span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground">No songs added today</p>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
};

const AppWithRouter: React.FC = () => (
  <Router>
    <Routes>
      <Route path="/admin" element={<AdminPage />} />
      <Route path="/" element={<App />} />
    </Routes>
  </Router>
);

export default AppWithRouter;
