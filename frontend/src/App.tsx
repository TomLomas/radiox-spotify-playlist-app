import React, { useState, useEffect, useRef } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import AdminPage from './AdminPage';
import { Song, AdminStats } from './types';

// UI Components
const Button: React.FC<{ onClick?: () => void; accent: string; children: React.ReactNode; type?: 'button' | 'submit' | 'reset' }> = ({ onClick, accent, children, type = 'button' }) => (
  <button
    onClick={onClick}
    type={type}
    className="px-4 py-2 rounded-lg border transition-colors"
    style={{ borderColor: accent, color: accent }}
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

  const handlePlayPause = () => {
    setIsPlaying((prev) => !prev);
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <Router>
      <Routes>
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/" element={
          <div className="min-h-screen bg-background text-foreground flex flex-col items-center">
            {/* Logo */}
            <div className="mt-8 mb-6 flex flex-col items-center">
              <img src="/x-purple.png" alt="Radio X" className="w-24 h-24 drop-shadow-lg" />
              <div className="flex gap-4 mt-4">
                <Button onClick={toggleTheme} accent={accent}>
                  {theme === 'dark' ? '🌞' : '🌙'}
                </Button>
                <Button onClick={() => window.location.href = '/admin'} accent={accent}>
                  Admin Controls
                </Button>
              </div>
            </div>

            {/* Main Row: Playing + Last Song Added */}
            <div className="flex flex-col md:flex-row gap-6 mb-8 w-full max-w-4xl justify-center">
              {/* Playing Card */}
              <Card className="flex-1 flex flex-col items-center justify-center p-6 min-w-[260px]">
                <h2 className="text-xl font-semibold mb-2">Playing</h2>
                <p className="text-2xl mb-4">{status?.current_song || 'Nothing playing'}</p>
                <div className="flex items-center gap-4 mt-2">
                  <Button onClick={handlePlayPause} accent={accent}>
                    {isPlaying ? '⏸ Pause' : '▶️ Play'}
                  </Button>
                  <span className="text-lg font-mono">{formatTime(timer)}</span>
                </div>
              </Card>
              {/* Last Song Added Card */}
              <Card className="flex-1 flex flex-col items-center justify-center p-6 min-w-[260px]">
                <h2 className="text-xl font-semibold mb-2">Last Song Added:</h2>
                <p className="text-2xl">
                  {status?.last_song_added 
                    ? `${status.last_song_added.radio_title} - ${status.last_song_added.radio_artist}`
                    : 'No songs added yet'}
                </p>
              </Card>
            </div>

            {/* Statistics Card */}
            <div className="w-full max-w-4xl mb-8">
              <Card className="p-6">
                <h2 className="text-xl font-semibold mb-4">Statistics</h2>
                {/* Performance Stats */}
                <div>
                  <h3 className="text-lg font-semibold mb-2">Performance Stats</h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                    <div>
                      <p className="text-sm text-muted-foreground">Total Songs Added</p>
                      <p className="text-lg">{stats?.total_songs_added ?? 'N/A'}</p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">Total Failures</p>
                      <p className="text-lg">{stats?.total_failures ?? 'N/A'}</p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">Success Rate</p>
                      <p className="text-lg">{stats?.success_rate != null ? `${stats.success_rate}%` : 'N/A'}</p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">Avg Songs/Day</p>
                      <p className="text-lg">{stats?.average_songs_per_day ?? 'N/A'}</p>
                    </div>
                  </div>
                </div>
                <hr className="my-4 border-t border-gray-300 dark:border-gray-700" />
                {/* Song Insights */}
                <div>
                  <h3 className="text-lg font-semibold mb-2">Song Insights</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
                    <div>
                      <p className="text-sm text-muted-foreground">Average Duration</p>
                      <p className="text-lg">
                        {stats?.average_duration 
                          ? `${Math.floor(stats.average_duration / 60)}:${String(Math.round(stats.average_duration % 60)).padStart(2, '0')}`
                          : 'N/A'}
                      </p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">Decade Spread</p>
                      <p className="text-lg">
                        {stats?.decade_spread 
                          ? Object.entries(stats.decade_spread)
                              .map(([decade, percent]) => `${decade}: ${percent}%`)
                              .join(', ')
                          : 'N/A'}
                      </p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">Newest Song</p>
                      <p className="text-lg">
                        {stats?.newest_song 
                          ? `${stats.newest_song.radio_title} (${stats.newest_song.year})`
                          : 'N/A'}
                      </p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">Oldest Song</p>
                      <p className="text-lg">
                        {stats?.oldest_song 
                          ? `${stats.oldest_song.radio_title} (${stats.oldest_song.year})`
                          : 'N/A'}
                      </p>
                    </div>
                  </div>
                </div>
                <hr className="my-4 border-t border-gray-300 dark:border-gray-700" />
                {/* Service Status */}
                <div>
                  <h3 className="text-lg font-semibold mb-2">Service Status</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <p className="text-sm text-muted-foreground">Last Check</p>
                      <p className="text-lg">{lastCheckComplete ? new Date(lastCheckComplete).toLocaleString() : 'N/A'}</p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">Next Check</p>
                      <p className="text-lg">{nextCheckTime ? new Date(nextCheckTime).toLocaleString() : 'N/A'}</p>
                    </div>
                  </div>
                </div>
              </Card>
            </div>

            {/* Added Today */}
            <div className="w-full max-w-4xl">
              <Card>
                <h2 className="text-xl font-semibold mb-4 p-6 pb-0">Added Today</h2>
                <div className="p-6 pt-0">
                  {dailyAdded.length > 0 ? (
                    <ul className="space-y-2">
                      {dailyAdded.map((song, index) => (
                        <li key={index} className="flex items-center gap-2">
                          <span className="text-accent">•</span>
                          {song.radio_title}
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
        } />
      </Routes>
    </Router>
  );
};

export default App;
