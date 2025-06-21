import React from 'react';

interface StatsPanelProps {
  stats: {
    playlist_size: number;
    max_playlist_size: number;
    top_artists: [string, number][];
    unique_artists: number;
    decade_spread: [string, string][];
    success_rate: string;
    service_paused: boolean;
    paused_reason: string;
  };
}

export const StatsPanel: React.FC<StatsPanelProps> = ({ stats }) => {
  return (
    <div className="bg-gray-800 shadow rounded-lg p-6">
      <h2 className="text-lg font-semibold text-white mb-4">Statistics</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <div className="bg-gray-700 p-4 rounded-lg">
          <h3 className="text-sm font-medium text-gray-300">Playlist Size</h3>
          <p className="mt-1 text-2xl font-semibold text-white">{stats.playlist_size}/{stats.max_playlist_size}</p>
        </div>
        <div className="bg-gray-700 p-4 rounded-lg">
          <h3 className="text-sm font-medium text-gray-300">Success Rate</h3>
          <p className="mt-1 text-2xl font-semibold text-white">{stats.success_rate}</p>
        </div>
        <div className="bg-gray-700 p-4 rounded-lg">
          <h3 className="text-sm font-medium text-gray-300">Unique Artists</h3>
          <p className="mt-1 text-2xl font-semibold text-white">{stats.unique_artists}</p>
        </div>
        <div className="bg-gray-700 p-4 rounded-lg min-h-[180px] flex flex-col">
          <h3 className="text-sm font-medium text-gray-300">Top Artists</h3>
          <ol className="mt-1 text-sm text-white flex-1 flex flex-col justify-start space-y-1">
            {Array.isArray(stats.top_artists) && stats.top_artists.length > 0 ? (
              stats.top_artists.map(([artist, count], idx) => (
                <li key={artist} className="flex justify-between items-center">
                  <span className="font-semibold">{idx + 1}. {artist}</span>
                  <span className="ml-2 text-purple-400">{count}</span>
                </li>
              ))
            ) : (
              <li className="text-gray-400">N/A</li>
            )}
          </ol>
        </div>
        <div className="bg-gray-700 p-4 rounded-lg min-h-[180px] flex flex-col">
          <h3 className="text-sm font-medium text-gray-300">Decade Spread</h3>
          <ol className="mt-1 text-sm text-white flex-1 flex flex-col justify-start space-y-1">
            {Array.isArray(stats.decade_spread) && stats.decade_spread.length > 0 ? (
              stats.decade_spread.map(([decade, percentage], idx) => (
                <li key={decade} className="flex justify-between items-center">
                  <span className="font-semibold">{idx + 1}. {decade}</span>
                  <span className="ml-2 text-purple-400">{percentage}</span>
                </li>
              ))
            ) : (
              <li className="text-gray-400">N/A</li>
            )}
          </ol>
        </div>
        <div className="bg-gray-700 p-4 rounded-lg">
          <h3 className="text-sm font-medium text-gray-300">Service Status</h3>
          <p className="mt-1 text-sm text-white truncate">
            {stats.service_paused ? `Paused (${stats.paused_reason})` : 'Running'}
          </p>
        </div>
      </div>
    </div>
  );
}; 