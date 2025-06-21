import React from 'react';

interface SongHistoryProps {
  dailyAdded: Array<{
    radio_title: string;
    radio_artist: string;
    spotify_id: string;
    release_date: string;
    album_art_url: string;
    album_name: string;
    added_at: string;
  }>;
  dailyFailed: Array<{
    radio_title: string;
    radio_artist: string;
    reason: string;
  }>;
}

export const SongHistory: React.FC<SongHistoryProps> = ({ dailyAdded, dailyFailed }) => {
  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp * 1000); // Convert Unix timestamp to milliseconds
    return date.toLocaleTimeString('en-GB', { 
      hour: '2-digit', 
      minute: '2-digit',
      second: '2-digit',
      hour12: false 
    });
  };

  const getYear = (dateString: string) => {
    if (!dateString || dateString.length < 4) return 'N/A';
    return dateString.substring(0, 4);
  };

  return (
    <div className="space-y-8">
      <div>
        <h3 className="text-lg font-semibold mb-3 text-purple-400">Successfully Added</h3>
        <div className="bg-gray-800 rounded-lg shadow-md overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-700">
              <thead className="bg-gray-900">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Time</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Track & Artist</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Album</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Year</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Listen</th>
                </tr>
              </thead>
              <tbody className="bg-gray-800 divide-y divide-gray-700">
                {[...dailyAdded].reverse().map((song, index) => (
                  <tr key={index} className="hover:bg-gray-700 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-400">
                      {formatTime(Number(song.added_at))}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <img className="h-10 w-10 rounded-md shadow" src={song.album_art_url} alt="Album Art" />
                        <div className="ml-4">
                          <div className="text-sm font-semibold text-white">{song.radio_title}</div>
                          <div className="text-sm text-gray-400">{song.radio_artist}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-400 truncate max-w-xs">{song.album_name}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-400">{getYear(song.release_date)}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <a 
                        href={`https://open.spotify.com/track/${song.spotify_id}`}
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="text-green-400 hover:text-green-300 font-semibold"
                      >
                        Listen ›
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-lg font-semibold mb-3 text-purple-400">Failed to Add</h3>
        <div className="bg-gray-800 rounded-lg shadow-md overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-700">
              <thead className="bg-gray-900">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Track & Artist</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Reason</th>
                </tr>
              </thead>
              <tbody className="bg-gray-800 divide-y divide-gray-700">
                {[...dailyFailed].reverse().map((song, index) => (
                  <tr key={index} className="hover:bg-gray-700 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm font-semibold text-white">{song.radio_title}</div>
                      <div className="text-sm text-gray-400">{song.radio_artist}</div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-400">{song.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}; 