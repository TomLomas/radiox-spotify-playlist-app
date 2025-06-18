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
}

export const AdminPanel: React.FC<AdminPanelProps> = ({ appState, backendVersion, frontendVersion }) => {
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
    <div className="bg-gray-800 shadow rounded-lg p-6">
      <h2 className="text-lg font-semibold text-white mb-4">Admin Controls</h2>
      
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        <button
          onClick={handleForceCheck}
          className="bg-purple-500 text-white px-4 py-2 rounded hover:bg-purple-600 transition-colors"
        >
          Force Check
        </button>
        <button
          onClick={handleCheckDuplicates}
          className="bg-purple-500 text-white px-4 py-2 rounded hover:bg-purple-600 transition-colors"
        >
          Check Duplicates
        </button>
        <button
          onClick={handleSendSummary}
          className="bg-purple-500 text-white px-4 py-2 rounded hover:bg-purple-600 transition-colors"
        >
          Send Summary
        </button>
        <button
          onClick={handleRetryFailed}
          className="bg-purple-500 text-white px-4 py-2 rounded hover:bg-purple-600 transition-colors"
        >
          Retry Failed
        </button>
        <button
          onClick={handleSendDebugLog}
          className="bg-purple-500 text-white px-4 py-2 rounded hover:bg-purple-600 transition-colors"
        >
          Send Debug Logs
        </button>
      </div>

      <h3 className="text-md font-semibold text-white mb-2">State History</h3>
      <div className="bg-gray-700 rounded-lg overflow-hidden mb-6">
        <table className="min-w-full divide-y divide-gray-600">
          <thead className="bg-gray-600">
            <tr>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Time</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">State</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Reason</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-600">
            {appState.state_history.map((entry, index) => (
              <tr key={index} className="hover:bg-gray-600">
                <td className="px-4 py-2 text-sm text-gray-300">{formatTimestamp(entry.timestamp)}</td>
                <td className="px-4 py-2 text-sm text-gray-300">{entry.state}</td>
                <td className="px-4 py-2 text-sm text-gray-300">{entry.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="p-4 bg-gray-700 rounded-lg flex flex-col md:flex-row md:items-center md:space-x-8">
        <div>Frontend Version: <span className="text-purple-400">{frontendVersion}</span></div>
        <div>Backend Version: <span className="text-purple-400">{backendVersion}</span></div>
      </div>
    </div>
  );
}; 