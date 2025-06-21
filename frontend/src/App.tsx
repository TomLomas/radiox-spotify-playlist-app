import React, { useState, useEffect } from 'react';
import { StatusBar } from './components/StatusBar';
import { ControlPanel } from './components/ControlPanel';
import { StatsPanel } from './components/StatsPanel';
import { SongHistory } from './components/SongHistory';
import { AdminPanel } from './components/AdminPanel';

interface AppState {
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
  current_song: string | null;
  queue_size: number;
  daily_added: any[];
  daily_failed: any[];
  stats: {
    playlist_size: number;
    max_playlist_size: number;
    top_artists: [string, number][];
    unique_artists: number;
    decade_spread: [string, string][];
    success_rate: string;
    service_paused: boolean;
    paused_reason: string;
  };
  seconds_until_next_check: number;
  service_state: string;
  state_history: Array<{
    timestamp: string;
    state: string;
    reason: string;
  }>;
  last_check_time: number;
  is_checking: boolean;
  check_complete: boolean;
  last_check_complete_time: number;
  next_check_time: string | null;
  backend_version: string;
}

const FRONTEND_VERSION = "1.1.1";

function App() {
  const [appState, setAppState] = useState<AppState | null>(null);
  const [activeTab, setActiveTab] = useState('status');
  const [logs, setLogs] = useState<string[]>([]);

  // Fetch status from backend
  const fetchStatus = async () => {
    try {
      const response = await fetch('/status');
      const data = await response.json();
      const safeStats = {
        playlist_size: data.stats?.playlist_size ?? 0,
        max_playlist_size: data.stats?.max_playlist_size ?? 500,
        top_artists: Array.isArray(data.stats?.top_artists) ? data.stats.top_artists : [],
        unique_artists: data.stats?.unique_artists ?? 0,
        decade_spread: Array.isArray(data.stats?.decade_spread) ? data.stats.decade_spread : [],
        success_rate: data.stats?.success_rate ?? "0%",
        service_paused: data.stats?.service_paused ?? false,
        paused_reason: data.stats?.paused_reason ?? "none"
      };
      setAppState({ ...data, stats: safeStats });
    } catch (error) {
      console.error('Error fetching status:', error);
    }
  };

  // Initialize app state and start listening for SSE
  useEffect(() => {
    fetchStatus(); // Initial fetch

    console.log('Setting up SSE connection...');
    const eventSource = new EventSource('/stream');

    eventSource.onopen = () => {
      console.log('SSE connection opened successfully');
    };

    eventSource.addEventListener('new_log', (event) => {
      console.log('Received new_log event:', event.data);
      const { log_entry } = JSON.parse(event.data);
      setLogs(prevLogs => [log_entry, ...prevLogs.slice(0, 99)]);
    });

    eventSource.addEventListener('state_change', (event) => {
      console.log('Received state_change event:', event.data);
      const { state, reason } = JSON.parse(event.data);
      setAppState(prevState => {
        if (!prevState) return null;
        return {
          ...prevState,
          service_state: state,
          stats: { ...prevState.stats, service_paused: state === 'paused', paused_reason: reason }
        };
      });
    });

    eventSource.addEventListener('status_update', (event) => {
      console.log('Received status_update event:', event.data);
      const data = JSON.parse(event.data);
      // If it's a timer update, just refresh the status to get updated countdown
      if (data.timer_update || data.last_check_complete_time) {
        fetchStatus();
      }
    });

    eventSource.addEventListener('test', (event) => {
      console.log('Received test event:', event.data);
    });

    eventSource.onerror = (err) => {
      console.error('EventSource failed:', err);
      eventSource.close();
    };

    return () => {
      console.log('Closing SSE connection');
      eventSource.close();
    };
  }, []);

  const handleForceCheck = async () => {
    try {
      const response = await fetch('/force_check', { method: 'POST' });
      if (response.ok) {
        console.log('Force check initiated');
      } else {
        console.error('Force check failed');
      }
    } catch (error) {
      console.error('Error during force check:', error);
    }
  };

  const testSSE = async () => {
    try {
      const response = await fetch('/test_sse');
      const result = await response.text();
      console.log('SSE test result:', result);
    } catch (error) {
      console.error('SSE test failed:', error);
    }
  };

  const handleResume = async () => {
    try {
      const response = await fetch('/resume', { method: 'POST' });
      if (response.ok) {
        console.log('Service resumed');
        fetchStatus(); // Refresh status
      } else {
        console.error('Resume failed');
      }
    } catch (error) {
      console.error('Error resuming service:', error);
    }
  };

  const handlePause = async () => {
    try {
      const response = await fetch('/pause', { method: 'POST' });
      if (response.ok) {
        console.log('Service paused');
        fetchStatus(); // Refresh status
      } else {
        console.error('Pause failed');
      }
    } catch (error) {
      console.error('Error pausing service:', error);
    }
  };

  if (!appState) {
    return (
      <div className="min-h-screen bg-gray-900 text-white flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-purple-500"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <div className="container mx-auto px-4 py-8">
        <div className="flex space-x-4 mb-6">
          <button
            onClick={() => setActiveTab('status')}
            className={`px-4 py-2 rounded-lg ${
              activeTab === 'status'
                ? 'bg-purple-600 text-white'
                : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
            }`}
          >
            Status
          </button>
          <button
            onClick={() => setActiveTab('admin')}
            className={`px-4 py-2 rounded-lg ${
              activeTab === 'admin'
                ? 'bg-purple-600 text-white'
                : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
            }`}
          >
            Admin
          </button>
        </div>

        {activeTab === 'status' && (
          <div className="space-y-6">
            <StatusBar 
              serviceState={appState.service_state}
              pausedReason={appState.stats.paused_reason}
              secondsUntilNextCheck={appState.seconds_until_next_check}
              isChecking={appState.is_checking}
              checkComplete={appState.check_complete}
              lastCheckTime={appState.last_check_time}
              lastCheckCompleteTime={appState.last_check_complete_time}
              nextCheckTime={appState.next_check_time || ''}
            />
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <ControlPanel appState={appState} />
              <StatsPanel stats={appState.stats} />
            </div>
            <div className="mt-8">
              <h2 className="text-xl font-semibold mb-4 text-purple-400">Today's History</h2>
              <SongHistory dailyAdded={appState.daily_added} dailyFailed={appState.daily_failed} />
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleResume}
                disabled={appState.service_state === 'running'}
                className="bg-green-500 hover:bg-green-600 disabled:bg-gray-400 text-white px-4 py-2 rounded"
              >
                Resume Service
              </button>
              <button
                onClick={handlePause}
                disabled={appState.service_state === 'paused'}
                className="bg-red-500 hover:bg-red-600 disabled:bg-gray-400 text-white px-4 py-2 rounded"
              >
                Pause Service
              </button>
              <button
                onClick={handleForceCheck}
                className="bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded"
              >
                Force Check
              </button>
              <button
                onClick={testSSE}
                className="bg-purple-500 hover:bg-purple-600 text-white px-4 py-2 rounded"
              >
                Test SSE
              </button>
            </div>
          </div>
        )}

        {activeTab === 'admin' && (
          <div className="mt-6">
            <AdminPanel appState={{
              service_state: appState.service_state,
              queue_size: appState.queue_size,
              state_history: appState.state_history
            }} backendVersion={appState.backend_version} frontendVersion={FRONTEND_VERSION} />
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
