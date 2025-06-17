import React from 'react';

interface ControlPanelProps {
  appState: {
    last_song_added: {
      radio_title: string;
      radio_artist: string;
      spotify_title: string;
      spotify_artist: string;
      spotify_id: string;
      release_date: string;
      album_art_url: string;
    } | null;
    service_state: string;
  };
}

export const ControlPanel: React.FC<ControlPanelProps> = ({ appState }) => {
  const handlePauseResume = async () => {
    try {
      await fetch('/admin/pause_resume', { method: 'POST' });
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

  return (
    <div className="bg-gray-800 shadow rounded-lg p-6">
      <h2 className="text-lg font-semibold text-white mb-4">Last Song Added</h2>
      {appState.last_song_added ? (
        <div className="flex items-center space-x-4">
          {appState.last_song_added.album_art_url && (
            <img
              src={appState.last_song_added.album_art_url}
              alt="Album Art"
              className="w-16 h-16 rounded-lg shadow-sm"
            />
          )}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-white truncate">
              {appState.last_song_added.radio_title}
            </p>
            <p className="text-sm text-gray-300 truncate">
              {appState.last_song_added.radio_artist}
            </p>
            <p className="text-xs text-gray-400 mt-1">
              Added to Spotify as: {appState.last_song_added.spotify_title}
            </p>
          </div>
        </div>
      ) : (
        <p className="text-sm text-gray-300">No songs added yet</p>
      )}

      <div className="mt-6 flex space-x-4">
        <button
          onClick={handlePauseResume}
          className={`${
            appState.service_state === 'playing'
              ? 'bg-red-500 hover:bg-red-600'
              : 'bg-purple-500 hover:bg-purple-600'
          } text-white px-4 py-2 rounded transition-colors`}
        >
          {appState.service_state === 'playing' ? 'Pause Service' : 'Resume Service'}
        </button>
        <button
          onClick={handleForceCheck}
          className="bg-purple-500 text-white px-4 py-2 rounded hover:bg-purple-600 transition-colors"
        >
          Force Check
        </button>
      </div>
    </div>
  );
}; 