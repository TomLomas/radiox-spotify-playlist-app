import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Song } from './types';

// UI Components
const Button: React.FC<{ onClick?: () => void; accent: string; children: React.ReactNode; type?: 'button' | 'submit' | 'reset'; disabled?: boolean }> = ({ onClick, accent, children, type = 'button', disabled }) => (
  <button
    onClick={onClick}
    type={type}
    className="px-4 py-2 rounded-lg border transition-colors"
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

const AdminPage: React.FC = () => {
  const navigate = useNavigate();
  const [theme, setTheme] = useState<'light' | 'dark'>('dark');
  const [failedSongs, setFailedSongs] = useState<Song[]>([]);
  const [showToast, setShowToast] = useState(false);
  const [toastMsg, setToastMsg] = useState('');
  const [checkInterval, setCheckInterval] = useState('02:00');
  const [duplicateCheckInterval, setDuplicateCheckInterval] = useState('30:00');
  const [maxPlaylistSize, setMaxPlaylistSize] = useState(500);
  const accent = theme === 'dark' ? '#9333ea' : '#22c55e';

  // Dark mode: toggle class on <body>
  useEffect(() => {
    document.body.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const statsRes = await fetch('/admin/stats');
        const statsData = await statsRes.json();
        setFailedSongs(statsData.daily_failed || []);
      } catch (error) {
        console.error('Error fetching data:', error);
      }
    };
    fetchData();
  }, []);

  const handleSettingsSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // Here you would POST to /admin/settings if implemented
    setToastMsg('Settings saved (not implemented)');
    setShowToast(true);
  };

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
      <div className="container mx-auto px-4 py-8 max-w-4xl">
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

        {/* Script Settings */}
        <Card className="mb-8 p-6">
          <h2 className="text-xl font-semibold mb-4">Script Settings</h2>
          <form onSubmit={handleSettingsSubmit} className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div>
              <label className="block text-sm font-medium mb-1">Check Interval (mm:ss)</label>
              <input
                type="text"
                value={checkInterval}
                onChange={e => setCheckInterval(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg"
                pattern="^\d{1,2}:\d{2}$"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Duplicate Check Interval (mm:ss)</label>
              <input
                type="text"
                value={duplicateCheckInterval}
                onChange={e => setDuplicateCheckInterval(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg"
                pattern="^\d{1,2}:\d{2}$"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Max Playlist Size</label>
              <input
                type="number"
                value={maxPlaylistSize}
                onChange={e => setMaxPlaylistSize(Number(e.target.value))}
                className="w-full px-3 py-2 border rounded-lg"
                min={1}
                max={1000}
                required
              />
            </div>
            <div className="md:col-span-3 flex justify-end">
              <Button type="submit" accent={accent}>Save Settings</Button>
            </div>
          </form>
        </Card>

        {/* Admin Actions */}
        <Card className="mb-8 p-6">
          <h2 className="text-xl font-semibold mb-4">Admin Actions</h2>
          <div className="flex flex-wrap gap-4">
            <Button onClick={() => adminAction('force_check')} accent={accent}>Check Now</Button>
            <Button onClick={() => adminAction('retry_failed')} accent={accent}>Retry Failed Songs</Button>
            <Button onClick={() => adminAction('force_duplicates')} accent={accent}>Check Duplicates</Button>
            <Button onClick={() => adminAction('send_debug_log')} accent={accent}>Send Debug Log</Button>
          </div>
        </Card>

        {/* Failed Songs */}
        <Card className="p-6 max-h-96 overflow-y-auto">
          <h2 className="text-xl font-semibold mb-4">Failed Songs</h2>
          {failedSongs.length > 0 ? (
            <div className="space-y-4">
              {failedSongs.map((song, index) => (
                <div key={index} className="flex items-center gap-4 border-b border-gray-200 dark:border-gray-700 pb-4">
                  {song.album_art_url && (
                    <img src={song.album_art_url} alt="Album Art" className="w-10 h-10 rounded shadow" />
                  )}
                  <div>
                    <p className="font-medium">{song.radio_title}</p>
                    <p className="text-sm text-muted-foreground">{song.radio_artist}</p>
                    <p className="text-sm text-red-500">Failed: {song.reason}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p>No failed songs</p>
          )}
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