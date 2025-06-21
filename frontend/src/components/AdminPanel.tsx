import React from 'react';

interface AdminPanelProps {
  appState: {
    service_state: string;
    queue_size: number;
    state_history: Array<{
      timestamp: string;
      state: string;
      reason: string;
    }>;
  };
  backendVersion: string;
  frontendVersion: string;
  onTestSSE: () => void;
}

export const AdminPanel: React.FC<AdminPanelProps> = ({ appState, backendVersion, frontendVersion, onTestSSE }) => {
  const handleForceCheck = async () => {
    try {
      await fetch('/admin/force_check', { method: 'POST' });
    } catch (error) {
      console.error('Error forcing check:', error);
    }
  };

  const handleCheckDuplicates = async () => {
    try {
      await fetch('/admin/force_duplicates', { method: 'POST' });
    } catch (error) {
      console.error('Error checking duplicates:', error);
    }
  };

  const handleSendSummary = async () => {
    try {
      await fetch('/admin/send_summary', { method: 'POST' });
    } catch (error) {
      console.error('Error sending summary:', error);
    }
  };

  const handleRetryFailed = async () => {
    try {
      await fetch('/admin/retry_failed', { method: 'POST' });
    } catch (error) {
      console.error('Error retrying failed songs:', error);
    }
  };

  const handleSendDebugLog = async () => {
    try {
      await fetch('/admin/send_debug_log', { method: 'POST' });
    } catch (error) {
      console.error('Error sending debug log:', error);
    }
  };

  const formatTimestamp = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString();
  };

  return (
    <div className="space-y-8">
      {/* Admin Controls Card */}
      <div className="bg-gray-800 shadow rounded-lg p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Admin Controls</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <button
            onClick={handleForceCheck}
            className="bg-purple-500 text-white px-4 py-2 rounded-lg font-semibold hover:bg-purple-600 transition-colors shadow"
          >
            Force Check
          </button>
          <button
            onClick={handleCheckDuplicates}
            className="bg-purple-500 text-white px-4 py-2 rounded-lg font-semibold hover:bg-purple-600 transition-colors shadow"
          >
            Check Duplicates
          </button>
          <button
            onClick={handleSendSummary}
            className="bg-purple-500 text-white px-4 py-2 rounded-lg font-semibold hover:bg-purple-600 transition-colors shadow"
          >
            Send Summary
          </button>
          <button
            onClick={handleRetryFailed}
            className="bg-purple-500 text-white px-4 py-2 rounded-lg font-semibold hover:bg-purple-600 transition-colors shadow"
          >
            Retry Failed
          </button>
          <button
            onClick={handleSendDebugLog}
            className="bg-purple-500 text-white px-4 py-2 rounded-lg font-semibold hover:bg-purple-600 transition-colors shadow"
          >
            Send Debug Logs
          </button>
          <button
            onClick={onTestSSE}
            className="bg-indigo-500 text-white px-4 py-2 rounded-lg font-semibold hover:bg-indigo-600 transition-colors shadow"
          >
            Test SSE
          </button>
        </div>
      </div>

      {/* State History Card */}
      <div className="bg-gray-800 shadow rounded-lg p-6">
        <h3 className="text-lg font-semibold text-white mb-4">State History</h3>
        <div className="bg-gray-700 rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-600">
              <thead className="bg-gray-700">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Time</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">State</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-600">
                {appState.state_history.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-6 py-4 text-center text-gray-400">No state history available.</td>
                  </tr>
                ) : (
                  appState.state_history.map((entry, index) => (
                    <tr key={index} className="hover:bg-gray-600">
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{formatTimestamp(entry.timestamp)}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{entry.state}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{entry.reason}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Version Info Card */}
      <div className="bg-gray-800 shadow rounded-lg p-6 flex flex-col items-center">
        <h3 className="text-lg font-semibold text-white mb-4">Version Info</h3>
        <div className="flex flex-col md:flex-row md:space-x-8 w-full max-w-xl justify-center">
          <div className="text-sm text-gray-300 font-semibold mb-2 md:mb-0">Frontend Version: <span className="text-purple-400">{frontendVersion}</span></div>
          <div className="text-sm text-gray-300 font-semibold">Backend Version: <span className="text-purple-400">{backendVersion}</span></div>
        </div>
      </div>
    </div>
  );
}; 