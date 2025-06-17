import React from 'react';

interface ControlPanelProps {
  appState: {
    lastSongAdded: {
      radio_title: string;
      radio_artist: string;
      album_art_url?: string;
      timestamp: string;
    } | null;
    service_state: string;
  };
}

export const ControlPanel: React.FC<ControlPanelProps> = ({ appState }) => {
  const handlePauseResume = async () => {
    const endpoint = appState.service_state === 'playing' ? '/admin/pause' : '/admin/resume';
    try {
      await fetch(endpoint, { method: 'POST' });
    } catch (error) {
      console.error('Error toggling service state:', error);
    }
  };

  const handleForceCheck = async () => {
    try {
      await fetch('/admin/force_check', { method: 'POST' });
    } catch (error) {
      console.error('Error forcing check:', error);
    }
  };

  const formatTimestamp = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString();
  };

  return (
    <div className="bg-white shadow rounded-lg p-6">
      <h2 className="text-lg font-medium text-gray-900 mb-4">Control Panel</h2>
      
      {/* Last Added Song */}
      <div className="mb-6">
        <h3 className="text-sm font-medium text-gray-500 mb-2">Last Added Song</h3>
        {appState.lastSongAdded ? (
          <div className="flex items-center space-x-4">
            {appState.lastSongAdded.album_art_url && (
              <img 
                src={appState.lastSongAdded.album_art_url} 
                alt="Album Art" 
                className="w-16 h-16 rounded-lg shadow-sm"
              />
            )}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-900 truncate">
                {appState.lastSongAdded.radio_title}
              </p>
              <p className="text-sm text-gray-500 truncate">
                {appState.lastSongAdded.radio_artist}
              </p>
              <p className="text-xs text-gray-400">
                Added at {formatTimestamp(appState.lastSongAdded.timestamp)}
              </p>
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-500">No songs added yet</p>
        )}
      </div>

      {/* Control Buttons */}
      <div className="flex flex-wrap gap-3">
        <button
          onClick={handlePauseResume}
          className={`inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white ${
            appState.service_state === 'playing'
              ? 'bg-yellow-600 hover:bg-yellow-700'
              : 'bg-green-600 hover:bg-green-700'
          } focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500`}
        >
          {appState.service_state === 'playing' ? '⏸ Pause' : '▶ Resume'}
        </button>

        <button
          onClick={handleForceCheck}
          className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
        >
          🔄 Force Check
        </button>

        <button
          onClick={() => window.location.href = '/admin/force_duplicates'}
          className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-purple-600 hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-purple-500"
        >
          🎵 Check Duplicates
        </button>
      </div>
    </div>
  );
}; 