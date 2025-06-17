import React from 'react';

interface StatsPanelProps {
  appState: {
    stats: {
      top_artists: string;
      unique_artists: number;
      most_common_failure: string;
      success_rate: string;
    };
    queueSize: number;
  };
}

export const StatsPanel: React.FC<StatsPanelProps> = ({ appState }) => {
  return (
    <div className="bg-white shadow rounded-lg p-6">
      <h2 className="text-lg font-medium text-gray-900 mb-4">Statistics</h2>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Success Rate */}
        <div className="bg-green-50 rounded-lg p-4">
          <h3 className="text-sm font-medium text-green-800">Success Rate</h3>
          <p className="mt-1 text-2xl font-semibold text-green-900">
            {appState.stats.success_rate}
          </p>
        </div>

        {/* Queue Size */}
        <div className="bg-blue-50 rounded-lg p-4">
          <h3 className="text-sm font-medium text-blue-800">Queue Size</h3>
          <p className="mt-1 text-2xl font-semibold text-blue-900">
            {appState.queueSize}
          </p>
        </div>

        {/* Top Artists */}
        <div className="bg-purple-50 rounded-lg p-4">
          <h3 className="text-sm font-medium text-purple-800">Top Artists</h3>
          <p className="mt-1 text-sm text-purple-900">
            {appState.stats.top_artists}
          </p>
        </div>

        {/* Unique Artists */}
        <div className="bg-yellow-50 rounded-lg p-4">
          <h3 className="text-sm font-medium text-yellow-800">Unique Artists</h3>
          <p className="mt-1 text-2xl font-semibold text-yellow-900">
            {appState.stats.unique_artists}
          </p>
        </div>

        {/* Most Common Failure */}
        <div className="bg-red-50 rounded-lg p-4 md:col-span-2">
          <h3 className="text-sm font-medium text-red-800">Most Common Failure</h3>
          <p className="mt-1 text-sm text-red-900">
            {appState.stats.most_common_failure}
          </p>
        </div>
      </div>
    </div>
  );
}; 