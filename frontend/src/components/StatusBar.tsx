import React, { useState, useEffect } from 'react';

interface StatusBarProps {
  serviceState: string;
  pausedReason: string;
  secondsUntilNextCheck: number;
  isChecking: boolean;
  checkComplete: boolean;
  lastCheckTime: number;
  lastCheckCompleteTime: number;
  nextCheckTime: string;
}

export const StatusBar: React.FC<StatusBarProps> = ({
  serviceState,
  pausedReason,
  secondsUntilNextCheck,
  isChecking,
  checkComplete,
  lastCheckTime,
  lastCheckCompleteTime,
  nextCheckTime
}) => {
  const [localSecondsRemaining, setLocalSecondsRemaining] = useState(secondsUntilNextCheck);
  const [nextCheckTimeStr, setNextCheckTimeStr] = useState('');

  useEffect(() => {
    // Update local timer when backend sends new value
    setLocalSecondsRemaining(secondsUntilNextCheck);
  }, [secondsUntilNextCheck]);

  useEffect(() => {
    // Start countdown timer
    const timer = setInterval(() => {
      setLocalSecondsRemaining(prev => {
        if (prev <= 0) return 0;
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    // Update next check time string
    const updateNextCheckTime = () => {
      const now = new Date();
      const nextCheck = new Date(now.getTime() + localSecondsRemaining * 1000);
      setNextCheckTimeStr(nextCheck.toLocaleTimeString());
    };

    updateNextCheckTime();
    const timer = setInterval(updateNextCheckTime, 1000);

    return () => clearInterval(timer);
  }, [localSecondsRemaining]);

  const formatTime = (timestamp: number) => {
    return new Date(timestamp).toLocaleTimeString();
  };

  const getStatusColor = (state: string) => {
    switch (state) {
      case 'playing':
        return 'bg-purple-500';
      case 'paused':
        return 'bg-yellow-500';
      default:
        return 'bg-red-500';
    }
  };

  const getStatusText = (state: string) => {
    switch (state) {
      case 'playing':
        return 'Running';
      case 'paused':
        return pausedReason === 'out_of_hours' ? 'Out of Hours' : 'Paused';
      default:
        return 'Error';
    }
  };

  return (
    <div className="bg-gray-900 shadow rounded-lg p-4 mb-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <div className={`w-3 h-3 rounded-full ${getStatusColor(serviceState)}`} />
          <span className="text-white font-medium">{getStatusText(serviceState)}</span>
        </div>
        <div className="text-gray-400 text-sm">
          {isChecking ? (
            <span>Checking now...</span>
          ) : (
            <span>Next check at {nextCheckTimeStr}</span>
          )}
        </div>
      </div>
      {checkComplete && (
        <div className="mt-2 text-gray-400 text-sm">
          Last check completed at {formatTime(lastCheckCompleteTime)}
        </div>
      )}
    </div>
  );
}; 