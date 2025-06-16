import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import AdminPage from './AdminPage';
import { Song, AdminStats } from './types';

// UI Components
const Button: React.FC<{ onClick: () => void; accent: string; children: React.ReactNode }> = ({ onClick, accent, children }) => (
  <button
    onClick={onClick}
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

const App: React.FC = () => {
  const [theme, setTheme] = useState<'light' | 'dark'>('dark');
  const [status, setStatus] = useState<any>(null);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [dailyAdded, setDailyAdded] = useState<Song[]>([]);
  const accent = theme === 'dark' ? '#9333ea' : '#22c55e';

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
      } catch (error) {
        console.error('Error fetching data:', error);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const toggleTheme = () => {
    setTheme(theme === 'dark' ? 'light' : 'dark');
  };

  return (
    <Router>
      <Routes>
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/" element={
          <div className="min-h-screen bg-background text-foreground">
            <div className="container mx-auto px-4 py-8">
              <div className="flex justify-between items-center mb-8">
                <h1 className="text-3xl font-bold">Radio X Spotify Playlist</h1>
                <div className="flex gap-4">
                  <Button onClick={toggleTheme} accent={accent}>
                    {theme === 'dark' ? '🌞' : '🌙'}
                  </Button>
                  <Button onClick={() => window.location.href = '/admin'} accent={accent}>
                    Admin Controls
                  </Button>
                </div>
              </div>

              {/* Status Cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
                <Card className="flex flex-col items-center justify-center p-6">
                  <h2 className="text-xl font-semibold mb-2">Playing</h2>
                  <p className="text-2xl">{status?.current_song || 'Nothing playing'}</p>
                </Card>
                <Card className="flex flex-col items-center justify-center p-6">
                  <h2 className="text-xl font-semibold mb-2">Last Song Added:</h2>
                  <p className="text-2xl">{status?.last_added || 'No songs added yet'}</p>
                </Card>
              </div>

              {/* Statistics Card */}
              <Card className="mb-8 p-6">
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
                      <p className="text-lg">{status?.last_check_complete_time ? new Date(status.last_check_complete_time).toLocaleString() : 'N/A'}</p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">Next Check</p>
                      <p className="text-lg">{status?.next_check_time ? new Date(status.next_check_time).toLocaleString() : 'N/A'}</p>
                    </div>
                  </div>
                </div>
              </Card>

              {/* Added Today */}
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
