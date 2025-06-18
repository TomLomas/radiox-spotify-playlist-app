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
  backend_version: string;
}

const FRONTEND_VERSION = "1.0.0-beta-20240618";

function App() {
  const [appState, setAppState] = useState<AppState | null>(null);
  const [activeTab, setActiveTab] = useState('status');
  const [countdown, setCountdown] = useState<number | null>(null);
  const [lastCheckCompleteTime, setLastCheckCompleteTime] = useState<number | null>(null);
  const [backendVersion, setBackendVersion] = useState<string>("");

  // Fetch status from backend
  const fetchStatus = async () => {
    try {
      const response = await fetch('/status');
      const data = await response.json();
      const safeStats = {
        top_artists: data.stats?.top_artists ?? "N/A",
        unique_artists: data.stats?.unique_artists ?? 0,
        most_common_failure: data.stats?.most_common_failure ?? "N/A",
        success_rate: data.stats?.success_rate ?? "0%",
        service_paused: data.stats?.service_paused ?? false,
        paused_reason: data.stats?.paused_reason ?? "none"
      };
      const lct = typeof data.last_check_complete_time === 'number' 
        ? data.last_check_complete_time 
        : Date.now();
      setAppState({
        ...data,
        stats: safeStats,
        last_check_complete_time: lct,
        backend_version: data.backend_version || ""
      });
      setLastCheckCompleteTime(lct);
      setCountdown(data.seconds_until_next_check);
      setBackendVersion(data.backend_version || "");
    } catch (error) {
      console.error('Error fetching status:', error);
    }
  };

  // Initialize app state and start polling
  useEffect(() => {
    let isInitialized = false;
    let timer: NodeJS.Timeout | null = null;
    let checkTimer: NodeJS.Timeout | null = null;

    const initializeAndPoll = async () => {
      if (isInitialized) return;
      isInitialized = true;
      await fetchStatus();
    };

    initializeAndPoll();

    // Cleanup function
    return () => {
      if (timer) clearInterval(timer);
      if (checkTimer) clearTimeout(checkTimer);
    };
  }, []);

  // Countdown timer logic
  useEffect(() => {
    let timer: NodeJS.Timeout | null = null;
    let checkTimer: NodeJS.Timeout | null = null;

    if (countdown === null) return;

    if (countdown <= 0) {
      // When countdown hits zero, immediately fetch status
      fetchStatus();
      
      // Set up a check timer to verify if a new cycle completed
      checkTimer = setTimeout(async () => {
        try {
          const response = await fetch('/status');
          const data = await response.json();
          const lct = typeof data.last_check_complete_time === 'number' 
            ? data.last_check_complete_time 
            : Date.now();
          if (lct !== lastCheckCompleteTime) {
            // New cycle completed, update everything
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
              stats: safeStats,
              last_check_complete_time: lct
            });
            setLastCheckCompleteTime(lct);
            setCountdown(data.seconds_until_next_check);
          } else {
            // Not yet, check again in 30 seconds
            setCountdown(0);
          }
        } catch (error) {
          console.error('Error fetching status:', error);
          // On error, wait 30 seconds before retrying
          setCountdown(0);
        }
      }, 30000);
    } else {
      // Normal countdown
      timer = setInterval(() => {
        setCountdown(prev => (prev !== null ? prev - 1 : null));
      }, 1000);
    }

    // Cleanup function
    return () => {
      if (timer) clearInterval(timer);
      if (checkTimer) clearTimeout(checkTimer);
    };
  }, [countdown, lastCheckCompleteTime]);

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
              secondsUntilNextCheck={countdown ?? appState.seconds_until_next_check}
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
          </div>
        )}

        {activeTab === 'admin' && (
          <div className="mt-6">
            <div className="mb-4 p-4 bg-gray-800 rounded-lg flex flex-col md:flex-row md:items-center md:space-x-8">
              <div>Frontend Version: <span className="text-purple-400">{FRONTEND_VERSION}</span></div>
              <div>Backend Version: <span className="text-purple-400">{backendVersion}</span></div>
            </div>
            <AdminPanel appState={{
              service_state: appState.service_state,
              queue_size: appState.queue_size,
              state_history: appState.state_history
            }} backendVersion={backendVersion} frontendVersion={FRONTEND_VERSION} />
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
