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
      album_name: string;
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

  const lastSong = appState.last_song_added;

  return (
    <div className="bg-gray-800 shadow rounded-lg p-6 flex flex-col justify-between">
      <div>
        <h2 className="text-lg font-semibold text-white mb-4">Last Song Added</h2>
        {lastSong ? (
          <div className="flex items-start space-x-4">
            <img
              src={lastSong.album_art_url}
              alt="Album Art"
              className="w-24 h-24 rounded-lg shadow-sm"
            />
            <div className="flex-1 min-w-0">
              <p className="text-lg font-bold text-white truncate">{lastSong.radio_title}</p>
              <p className="text-md text-gray-300 truncate">{lastSong.radio_artist}</p>
              <p className="text-sm text-gray-400 mt-2">Album: {lastSong.album_name}</p>
              <p className="text-sm text-gray-400">Released: {lastSong.release_date}</p>
              <a 
                href={`https://open.spotify.com/track/${lastSong.spotify_id}`}
                target="_blank" 
                rel="noopener noreferrer"
                className="inline-block mt-3 bg-green-500 text-white px-3 py-1 rounded-full text-xs font-semibold hover:bg-green-600 transition-colors"
              >
                Listen on Spotify
              </a>
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-300">No songs added yet today.</p>
        )}
      </div>

      <div className="mt-6 border-t border-gray-700 pt-4">
        <h3 className="text-md font-semibold text-white mb-3">Service Controls</h3>
        <div className="flex space-x-4">
          <button
            onClick={handlePauseResume}
            className={`${
              appState.service_state === 'playing'
                ? 'bg-red-500 hover:bg-red-600'
                : 'bg-purple-500 hover:bg-purple-600'
            } text-white px-4 py-2 rounded-lg transition-colors font-semibold shadow-md`}
          >
            {appState.service_state === 'playing' ? 'Pause Service' : 'Resume Service'}
          </button>
          <button
            onClick={handleForceCheck}
            className="bg-purple-500 text-white px-4 py-2 rounded-lg hover:bg-purple-600 transition-colors font-semibold shadow-md"
          >
            Force Check
          </button>
        </div>
      </div>
    </div>
  );
}; 