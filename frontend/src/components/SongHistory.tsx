import React, { useState } from 'react';

interface Song {
  radio_title: string;
  radio_artist: string;
  album_art_url?: string;
  timestamp: string;
  reason?: string;
}

interface SongHistoryProps {
  dailyAdded: Song[];
  dailyFailed: Song[];
}

export const SongHistory: React.FC<SongHistoryProps> = ({ dailyAdded, dailyFailed }) => {
  const [activeTab, setActiveTab] = useState<'added' | 'failed'>('added');

  const formatTimestamp = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString();
  };

  return (
    <div className="bg-white shadow rounded-lg">
      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex">
          <button
            onClick={() => setActiveTab('added')}
            className={`${
              activeTab === 'added'
                ? 'border-green-500 text-green-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } w-1/2 py-4 px-1 text-center border-b-2 font-medium text-sm`}
          >
            Added Songs ({dailyAdded.length})
          </button>
          <button
            onClick={() => setActiveTab('failed')}
            className={`${
              activeTab === 'failed'
                ? 'border-red-500 text-red-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } w-1/2 py-4 px-1 text-center border-b-2 font-medium text-sm`}
          >
            Failed Songs ({dailyFailed.length})
          </button>
        </nav>
      </div>

      {/* Content */}
      <div className="p-6">
        {activeTab === 'added' ? (
          <div className="space-y-4">
            {dailyAdded.length > 0 ? (
              dailyAdded.map((song, index) => (
                <div key={index} className="flex items-center space-x-4 p-3 rounded-lg hover:bg-gray-50">
                  {song.album_art_url && (
                    <img
                      src={song.album_art_url}
                      alt="Album Art"
                      className="w-12 h-12 rounded-lg shadow-sm"
                    />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {song.radio_title}
                    </p>
                    <p className="text-sm text-gray-500 truncate">
                      {song.radio_artist}
                    </p>
                  </div>
                  <div className="text-xs text-gray-400">
                    {formatTimestamp(song.timestamp)}
                  </div>
                </div>
              ))
            ) : (
              <p className="text-sm text-gray-500 text-center py-4">No songs added today</p>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {dailyFailed.length > 0 ? (
              dailyFailed.map((song, index) => (
                <div key={index} className="flex items-center space-x-4 p-3 rounded-lg hover:bg-gray-50">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {song.radio_title}
                    </p>
                    <p className="text-sm text-gray-500 truncate">
                      {song.radio_artist}
                    </p>
                    {song.reason && (
                      <p className="text-xs text-red-500 mt-1">
                        {song.reason}
                      </p>
                    )}
                  </div>
                  <div className="text-xs text-gray-400">
                    {formatTimestamp(song.timestamp)}
                  </div>
                </div>
              ))
            ) : (
              <p className="text-sm text-gray-500 text-center py-4">No failed songs today</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}; 