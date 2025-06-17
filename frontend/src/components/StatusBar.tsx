import React from 'react';

interface StatusBarProps {
  appState: {
    currentSong: string | null;
    service_state: string;
    seconds_until_next_check: number;
    is_checking: boolean;
  };
}

export const StatusBar: React.FC<StatusBarProps> = ({ appState }) => {
  const formatTime = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
  };

  const getStatusColor = (state: string) => {
    switch (state) {
      case 'playing':
        return 'bg-green-100 text-green-800';
      case 'paused':
        return 'bg-yellow-100 text-yellow-800';
      case 'out_of_hours':
        return 'bg-gray-100 text-gray-800';
      default:
        return 'bg-blue-100 text-blue-800';
    }
  };

  const getStatusText = (state: string) => {
    switch (state) {
      case 'playing':
        return 'Active';
      case 'paused':
        return 'Paused';
      case 'out_of_hours':
        return 'Out of Hours';
      default:
        return state;
    }
  };

  return (
    <div className="bg-white shadow rounded-lg p-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Current Song */}
        <div className="flex flex-col">
          <h3 className="text-sm font-medium text-gray-500">Now Playing</h3>
          <p className="mt-1 text-lg font-semibold text-gray-900">
            {appState.currentSong || 'No song playing'}
          </p>
        </div>

        {/* Service Status */}
        <div className="flex flex-col">
          <h3 className="text-sm font-medium text-gray-500">Service Status</h3>
          <div className="mt-1 flex items-center">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusColor(appState.service_state)}`}>
              {getStatusText(appState.service_state)}
            </span>
            {appState.is_checking && (
              <span className="ml-2 inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                Checking...
              </span>
            )}
          </div>
        </div>

        {/* Next Check */}
        <div className="flex flex-col">
          <h3 className="text-sm font-medium text-gray-500">Next Check</h3>
          <p className="mt-1 text-lg font-semibold text-gray-900">
            {formatTime(appState.seconds_until_next_check)}
          </p>
        </div>
      </div>
    </div>
  );
}; 