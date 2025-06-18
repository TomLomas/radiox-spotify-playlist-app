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
  const [lastCheckTimeStr, setLastCheckTimeStr] = useState('');

  useEffect(() => {
    // Update local timer when backend sends new value
    setLocalSecondsRemaining(secondsUntilNextCheck);
  }, [secondsUntilNextCheck]);

  useEffect(() => {
    // Only start countdown timer if service is not paused
    if (serviceState !== 'paused') {
      const timer = setInterval(() => {
        setLocalSecondsRemaining(prev => {
          // If we hit 0, wait for the next value from backend
          if (prev <= 0) return 0;
          return prev - 1;
        });
      }, 1000);

      return () => clearInterval(timer);
    }
  }, [serviceState, secondsUntilNextCheck]);

  useEffect(() => {
    // Update next check time string only if service is not paused
    if (serviceState !== 'paused' && nextCheckTime) {
      const nextCheck = new Date(nextCheckTime);
      setNextCheckTimeStr(nextCheck.toLocaleTimeString());
    } else {
      setNextCheckTimeStr('--:--:--');
    }
  }, [nextCheckTime, serviceState]);

  useEffect(() => {
    // Update last check time string
    const updateLastCheckTime = () => {
      if (lastCheckCompleteTime) {
        const date = new Date(lastCheckCompleteTime * 1000); // Convert Unix timestamp to milliseconds
        setLastCheckTimeStr(date.toLocaleTimeString());
      }
    };

    updateLastCheckTime();
    const timer = setInterval(updateLastCheckTime, 1000);

    return () => clearInterval(timer);
  }, [lastCheckCompleteTime]);

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

  const formatCountdown = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
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
          ) : serviceState === 'paused' ? (
            <span>Service paused</span>
          ) : (
            <div className="flex items-center space-x-2">
              <span>Next check at {nextCheckTimeStr}</span>
              <span className="text-purple-400">({formatCountdown(localSecondsRemaining)})</span>
            </div>
          )}
        </div>
      </div>
      {checkComplete && serviceState !== 'paused' && (
        <div className="mt-2 text-gray-400 text-sm">
          Last check completed at {lastCheckTimeStr}
        </div>
      )}
    </div>
  );
}; 