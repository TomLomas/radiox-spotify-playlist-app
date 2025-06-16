import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
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

const AdminPage: React.FC = () => {
  const navigate = useNavigate();
  const [theme, setTheme] = useState<'light' | 'dark'>('dark');
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [failedSongs, setFailedSongs] = useState<Song[]>([]);
  const [showToast, setShowToast] = useState(false);
  const [toastMsg, setToastMsg] = useState('');
  const accent = theme === 'dark' ? '#9333ea' : '#22c55e';

  // Dark mode: toggle class on <body>
  useEffect(() => {
    document.body.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statsRes, failedRes] = await Promise.all([
          fetch('/admin/stats'),
          fetch('/admin/stats')  // Use the same endpoint, it includes failed songs
        ]);
        const statsData = await statsRes.json();
        setStats(statsData.stats);
        setFailedSongs(statsData.daily_failed || []);
      } catch (error) {
        console.error('Error fetching data:', error);
      }
    };
    fetchData();
  }, []);

  const adminAction = async (action: string) => {
    try {
      const response = await fetch(`/admin/${action}`, { method: 'POST' });
      if (response.ok) {
        setToastMsg(`${action} completed successfully`);
        setShowToast(true);
      } else {
        setToastMsg(`Failed to ${action}`);
        setShowToast(true);
      }
    } catch (error) {
      console.error(`Error performing ${action}:`, error);
      setToastMsg(`Error performing ${action}`);
      setShowToast(true);
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="container mx-auto px-4 py-8">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold">Admin Controls</h1>
          <div className="flex gap-4">
            <Button onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} accent={accent}>
              {theme === 'dark' ? '🌞' : '🌙'}
            </Button>
            <Button onClick={() => navigate('/')} accent={accent}>
              Back to Dashboard
            </Button>
          </div>
        </div>

        {/* Admin Actions */}
        <Card className="mb-8 p-6">
          <h2 className="text-xl font-semibold mb-4">Admin Actions</h2>
          <div className="flex flex-wrap gap-4">
            <Button onClick={() => adminAction('force_check')} accent={accent}>
              Check Now
            </Button>
            <Button onClick={() => adminAction('retry_failed')} accent={accent}>
              Retry Failed Songs
            </Button>
            <Button onClick={() => adminAction('force_duplicates')} accent={accent}>
              Check Duplicates
            </Button>
            <Button onClick={() => adminAction('pause_resume')} accent={accent}>
              Pause/Resume
            </Button>
          </div>
        </Card>

        {/* Stats */}
        <Card className="mb-8 p-6">
          <h2 className="text-xl font-semibold mb-4">Stats</h2>
          {stats ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <div>
                <p className="text-sm text-muted-foreground">Total Songs Added</p>
                <p className="text-lg">{stats.total_songs_added}</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Total Failures</p>
                <p className="text-lg">{stats.total_failures}</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Success Rate</p>
                <p className="text-lg">{stats.success_rate}%</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Average Songs/Day</p>
                <p className="text-lg">{stats.average_songs_per_day}</p>
              </div>
            </div>
          ) : (
            <p>Loading stats...</p>
          )}
        </Card>

        {/* Failed Songs */}
        <Card>
          <h2 className="text-xl font-semibold mb-4 p-6 pb-0">Failed Songs</h2>
          <div className="p-6 pt-0">
            {failedSongs.length > 0 ? (
              <div className="space-y-4">
                {failedSongs.map((song, index) => (
                  <div key={index} className="border-b border-gray-200 dark:border-gray-700 pb-4">
                    <p className="font-medium">{song.radio_title}</p>
                    <p className="text-sm text-muted-foreground">{song.radio_artist}</p>
                    <p className="text-sm text-red-500">Failed: {song.reason}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p>No failed songs</p>
            )}
          </div>
        </Card>
      </div>

      {/* Toast */}
      {showToast && (
        <div className="fixed bottom-4 right-4 bg-white dark:bg-gray-800 px-4 py-2 rounded-lg shadow-lg">
          {toastMsg}
        </div>
      )}
    </div>
  );
};

export default AdminPage; 