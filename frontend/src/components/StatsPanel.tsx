import React from 'react';

interface StatsPanelProps {
  stats: {
    top_artists: string;
    unique_artists: number;
    most_common_failure: string;
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
          <h3 className="text-sm font-medium text-gray-300">Success Rate</h3>
          <p className="mt-1 text-2xl font-semibold text-white">{stats.success_rate}</p>
        </div>
        <div className="bg-gray-700 p-4 rounded-lg">
          <h3 className="text-sm font-medium text-gray-300">Unique Artists</h3>
          <p className="mt-1 text-2xl font-semibold text-white">{stats.unique_artists}</p>
        </div>
        <div className="bg-gray-700 p-4 rounded-lg">
          <h3 className="text-sm font-medium text-gray-300">Top Artists</h3>
          <p className="mt-1 text-sm text-white truncate">{stats.top_artists}</p>
        </div>
        <div className="bg-gray-700 p-4 rounded-lg">
          <h3 className="text-sm font-medium text-gray-300">Most Common Failure</h3>
          <p className="mt-1 text-sm text-white truncate">{stats.most_common_failure}</p>
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