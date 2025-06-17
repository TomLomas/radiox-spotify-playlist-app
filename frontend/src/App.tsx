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
  } | null;
  current_song: string | null;
  queue_size: number;
  daily_added: any[];
  daily_failed: any[];
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
}

function App() {
  const [appState, setAppState] = useState<AppState | null>(null);
  const [isAdmin] = useState(false);
  const [activeTab] = useState('status');

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch('/status');
        const data = await response.json();
        // Defensive: ensure stats always has all properties
        const safeStats = {
          top_artists: data.stats?.top_artists ?? "N/A",
          unique_artists: data.stats?.unique_artists ?? 0,
          most_common_failure: data.stats?.most_common_failure ?? "N/A",
          success_rate: data.stats?.success_rate ?? "0%",
          service_paused: data.stats?.service_paused ?? false,
          paused_reason: data.stats?.paused_reason ?? "none"
        };
        setAppState({
          ...data,
          stats: safeStats
        });
      } catch (error) {
        console.error('Error fetching status:', error);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

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
          </div>
        )}

        <div className="mt-6">
          <SongHistory dailyAdded={appState.daily_added} dailyFailed={appState.daily_failed} />
        </div>

        {isAdmin && (
          <div className="mt-6">
            <AdminPanel appState={{
              service_state: appState.service_state,
              queue_size: appState.queue_size,
              state_history: appState.state_history
            }} />
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
