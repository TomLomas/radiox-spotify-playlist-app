import React from 'react';

interface SongHistoryProps {
  dailyAdded: Array<{
    radio_title: string;
    radio_artist: string;
    spotify_title: string;
    spotify_artist: string;
    spotify_id: string;
    release_date: string;
    album_art_url: string;
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

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold mb-3 text-purple-400">Successfully Added</h3>
        <div className="bg-gray-800 rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-700">
              <thead className="bg-gray-700">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Radio</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Time Added</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Release Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {dailyAdded.map((song, index) => (
                  <tr key={index} className="hover:bg-gray-700">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <img className="h-10 w-10 rounded" src={song.album_art_url} alt="" />
                        <div className="ml-4">
                          <div className="text-sm font-medium text-white">{song.radio_title}</div>
                          <div className="text-sm text-gray-400">{song.radio_artist}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-400">
                      {formatTime(Number(song.added_at))}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-400">
                      {song.release_date}
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
        <div className="bg-gray-800 rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-700">
              <thead className="bg-gray-700">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Radio</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {dailyFailed.map((song, index) => (
                  <tr key={index} className="hover:bg-gray-700">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm font-medium text-white">{song.radio_title}</div>
                      <div className="text-sm text-gray-400">{song.radio_artist}</div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-400">
                      {song.reason}
                    </td>
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