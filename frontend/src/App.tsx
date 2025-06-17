import React, { useState, useEffect } from 'react';
import { StatusBar } from './components/StatusBar';
import { ControlPanel } from './components/ControlPanel';
import { StatsPanel } from './components/StatsPanel';
import { SongHistory } from './components/SongHistory';
import { AdminPanel } from './components/AdminPanel';

interface AppState {
  lastSongAdded: any;
  currentSong: string | null;
  queueSize: number;
  dailyAdded: any[];
  dailyFailed: any[];
  stats: {
    top_artists: string;
    unique_artists: number;
    most_common_failure: string;
    success_rate: string;
    service_paused: boolean;
    paused_reason: string;
  };
  seconds_until_next_check: number;
  service_state: string;
  state_history: any[];
  last_check_time: number;
  is_checking: boolean;
  check_complete: boolean;
  last_check_complete_time: number;
  next_check_time: string | null;
}

function App() {
  const [appState, setAppState] = useState<AppState | null>(null);
  const [activeTab, setActiveTab] = useState('status');

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const response = await fetch('/status');
        const data = await response.json();
        setAppState(data);
      } catch (error) {
        console.error('Error fetching status:', error);
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  if (!appState) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-green-500"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900">
      <nav className="bg-gray-800 shadow-lg">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex">
              <div className="flex-shrink-0 flex items-center">
                <h1 className="text-2xl font-bold text-purple-500">Radio X → Spotify</h1>
              </div>
              <div className="hidden sm:ml-6 sm:flex sm:space-x-8">
                <button
                  onClick={() => setActiveTab('status')}
                  className={`${
                    activeTab === 'status'
                      ? 'border-purple-500 text-white'
                      : 'border-transparent text-gray-300 hover:border-gray-300 hover:text-white'
                  } inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium`}
                >
                  Status
                </button>
                <button
                  onClick={() => setActiveTab('history')}
                  className={`${
                    activeTab === 'history'
                      ? 'border-purple-500 text-white'
                      : 'border-transparent text-gray-300 hover:border-gray-300 hover:text-white'
                  } inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium`}
                >
                  History
                </button>
                <button
                  onClick={() => setActiveTab('admin')}
                  className={`${
                    activeTab === 'admin'
                      ? 'border-purple-500 text-white'
                      : 'border-transparent text-gray-300 hover:border-gray-300 hover:text-white'
                  } inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium`}
                >
                  Admin
                </button>
              </div>
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        <div className="px-4 py-6 sm:px-0">
          {activeTab === 'status' && (
            <div className="space-y-6">
              <StatusBar appState={appState} />
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <ControlPanel appState={appState} />
                <StatsPanel appState={appState} />
              </div>
            </div>
          )}
          
          {activeTab === 'history' && (
            <SongHistory dailyAdded={appState.dailyAdded} dailyFailed={appState.dailyFailed} />
          )}
          
          {activeTab === 'admin' && (
            <AdminPanel appState={appState} />
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
