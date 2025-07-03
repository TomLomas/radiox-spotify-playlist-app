import React, { useEffect, useState } from 'react';

interface Activity {
  timestamp: string;
  type: string;
  message: string;
  success: boolean | null;
  details?: Record<string, any>;
}

interface Stats {
  total_songs_processed: number;
  successful_adds: number;
  failed_searches: number;
  api_calls: number;
  uptime_seconds: number;
  uptime_formatted: string;
  success_rate: string;
  songs_per_hour: number;
}

const statusColor = (activities: Activity[]): string => {
  if (!activities.length) return 'bg-gray-400';
  const last = activities[0];
  if (last.type === 'error') return 'bg-red-500';
  if (last.type === 'search_failed' || last.type === 'add_failed') return 'bg-yellow-400';
  return 'bg-green-500';
};

const typeIcon = (type: string) => {
  switch (type) {
    case 'song_added': return '✅';
    case 'song_detected': return '🎵';
    case 'search_failed': return '❌';
    case 'add_failed': return '⚠️';
    case 'error': return '🚨';
    default: return 'ℹ️';
  }
};

const LiveActivityDashboard: React.FC = () => {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  // Poll /activity every 3 seconds
  useEffect(() => {
    let mounted = true;
    const fetchActivity = async () => {
      try {
        const res = await fetch('/activity');
        const data = await res.json();
        if (mounted) {
          setActivities(data.activities || []);
          setStats(data.stats || null);
          setLoading(false);
        }
      } catch (e) {
        // If error, show as disconnected
        if (mounted) setLoading(false);
      }
    };
    fetchActivity();
    const interval = setInterval(fetchActivity, 3000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  return (
    <div className="bg-gray-800 rounded-lg shadow p-6 mb-6 w-full">
      <div className="flex items-center mb-4">
        <span className={`inline-block w-3 h-3 rounded-full mr-2 ${statusColor(activities)}`}></span>
        <h2 className="text-xl font-bold text-white">Live Activity Dashboard</h2>
        <span className="ml-auto text-xs text-gray-400">{loading ? 'Connecting...' : 'Live'}</span>
      </div>
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4 text-center">
          <div>
            <div className="text-lg font-semibold text-green-400">{stats.success_rate}</div>
            <div className="text-xs text-gray-300">Success Rate</div>
          </div>
          <div>
            <div className="text-lg font-semibold text-blue-400">{stats.songs_per_hour.toFixed(2)}</div>
            <div className="text-xs text-gray-300">Songs/Hour</div>
          </div>
          <div>
            <div className="text-lg font-semibold text-gray-200">{stats.uptime_formatted}</div>
            <div className="text-xs text-gray-300">Uptime</div>
          </div>
          <div>
            <div className="text-lg font-semibold text-gray-200">{stats.total_songs_processed}</div>
            <div className="text-xs text-gray-300">Total Processed</div>
          </div>
        </div>
      )}
      <div className="h-64 overflow-y-auto border-t border-b border-gray-700 py-2 bg-gray-900 rounded">
        {activities.length === 0 && (
          <div className="text-center text-gray-500 py-8">No recent activity.</div>
        )}
        <ul>
          {activities.map((a, i) => (
            <li key={i} className="flex items-center py-2 px-2 border-b border-gray-700 last:border-b-0">
              <span className="text-xl mr-3">{typeIcon(a.type)}</span>
              <div className="flex-1">
                <div className="text-sm text-white">{a.message}</div>
                <div className="text-xs text-gray-400">{new Date(a.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default LiveActivityDashboard; 