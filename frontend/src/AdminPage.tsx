import React, { useState, useEffect, useCallback } from 'react';
import { Card, Button } from './App';

interface Song {
  radio_title: string;
  radio_artist: string;
  album_art_url?: string;
  reason?: string;
  [key: string]: any;
}

interface AdminStats {
  total_songs_added: number;
  total_failures: number;
  success_rate: number;
  average_songs_per_day: number;
  most_common_artist: string;
  most_common_failure: string;
  last_check_time: string;
  next_check_time: string;
}

const AdminPage: React.FC = () => {
  const [dailyFailed, setDailyFailed] = useState<Song[]>([]);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [showToast, setShowToast] = useState(false);
  const [toastMsg, setToastMsg] = useState('');

  const triggerToast = (msg: string) => {
    setToastMsg(msg);
    setShowToast(true);
    setTimeout(() => setShowToast(false), 2500);
  };

  const adminAction = async (url: string, method: string = 'POST') => {
    try {
      const res = await fetch(url, { method });
      const text = await res.text();
      triggerToast(text);
      fetchAdminData();
    } catch (e) {
      triggerToast('Admin action failed');
    }
  };

  const fetchAdminData = useCallback(async () => {
    try {
      const response = await fetch('/admin/stats');
      if (!response.ok) {
        throw new Error('Failed to fetch admin data');
      }
      const data = await response.json();
      setStats(data.stats);
      setDailyFailed(data.daily_failed);
    } catch (error) {
      console.error('Error fetching admin data:', error);
      triggerToast('Failed to fetch admin data', 'error');
    }
  }, []);

  useEffect(() => {
    fetchAdminData();
  }, [fetchAdminData]);

  return (
    <div className="min-h-screen w-full bg-background-light dark:bg-background-dark transition-colors duration-300 p-8">
      <div className="max-w-6xl mx-auto">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold">Admin Controls</h1>
          <Button accent="#1DB954" onClick={() => window.location.href = '/'}>Back to Main</Button>
        </div>

        {/* Stats Overview */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <Card accent="#1DB954">
            <h2 className="text-xl font-bold mb-4">Performance Stats</h2>
            {stats && (
              <div className="text-left">
                <p>Total Songs Added: {stats.total_songs_added}</p>
                <p>Total Failures: {stats.total_failures}</p>
                <p>Success Rate: {stats.success_rate}%</p>
                <p>Avg Songs/Day: {stats.average_songs_per_day}</p>
              </div>
            )}
          </Card>

          <Card accent="#1DB954">
            <h2 className="text-xl font-bold mb-4">Common Patterns</h2>
            {stats && (
              <div className="text-left">
                <p>Most Common Artist: {stats.most_common_artist}</p>
                <p>Most Common Failure: {stats.most_common_failure}</p>
              </div>
            )}
          </Card>

          <Card accent="#1DB954">
            <h2 className="text-xl font-bold mb-4">Service Status</h2>
            {stats && (
              <div className="text-left">
                <p>Last Check: {stats.last_check_time}</p>
                <p>Next Check: {stats.next_check_time}</p>
              </div>
            )}
          </Card>
        </div>

        {/* Admin Actions */}
        <Card accent="#1DB954" className="mb-8">
          <h2 className="text-xl font-bold mb-4">Admin Actions</h2>
          <div className="flex flex-wrap gap-4 justify-center">
            <Button accent="#1DB954" onClick={() => adminAction('/admin/send_summary_email')}>Send Summary Email</Button>
            <Button accent="#1DB954" onClick={() => adminAction('/admin/retry_failed')}>Retry Failed Songs</Button>
            <Button accent="#1DB954" onClick={() => adminAction('/admin/check_duplicates')}>Check for Duplicates</Button>
            <Button accent="#1DB954" onClick={() => adminAction('/admin/force_check')}>Force Check</Button>
          </div>
        </Card>

        {/* Failed Songs */}
        <Card accent="#ef4444">
          <h2 className="text-xl font-bold mb-4">Failed Songs Today</h2>
          <div className="w-full">
            {dailyFailed.length > 0 ? (
              dailyFailed.map((song, index) => (
                <div key={index} className="flex items-start gap-4 mb-4 p-4 rounded-lg bg-gray-50 dark:bg-gray-800">
                  {song.album_art_url && (
                    <img src={song.album_art_url} alt="Album Art" className="w-16 h-16 rounded shadow" />
                  )}
                  <div className="flex-1">
                    <div className="font-semibold text-lg">{song.radio_title}</div>
                    <div className="text-gray-500">{song.radio_artist}</div>
                    {song.reason && (
                      <div className="mt-2 p-2 bg-red-100 dark:bg-red-900/30 rounded text-red-700 dark:text-red-300">
                        <strong>Error:</strong> {song.reason}
                      </div>
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

      {/* Toast Notification */}
      {showToast && (
        <div className="fixed bottom-4 right-4 bg-gray-800 text-white px-4 py-2 rounded-lg shadow-lg">
          {toastMsg}
        </div>
      )}
    </div>
  );
};

export default AdminPage; 