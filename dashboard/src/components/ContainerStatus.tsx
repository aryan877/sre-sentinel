import React from 'react';
import { Activity, AlertCircle, CheckCircle, RefreshCw } from 'lucide-react';

export interface ContainerStatusProps {
  name: string;
  status: 'healthy' | 'warning' | 'critical' | 'offline';
  cpuPercent: number;
  memoryPercent: number;
  restartCount: number;
  uptime?: string;
}

const statusConfig = {
  healthy: {
    color: 'text-green-500',
    bgColor: 'bg-green-500/10',
    borderColor: 'border-green-500/20',
    icon: CheckCircle,
    label: 'Healthy',
  },
  warning: {
    color: 'text-yellow-500',
    bgColor: 'bg-yellow-500/10',
    borderColor: 'border-yellow-500/20',
    icon: AlertCircle,
    label: 'Warning',
  },
  critical: {
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
    borderColor: 'border-red-500/20',
    icon: AlertCircle,
    label: 'Critical',
  },
  offline: {
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/10',
    borderColor: 'border-gray-600/20',
    icon: RefreshCw,
    label: 'Offline',
  },
};

export const ContainerStatus: React.FC<ContainerStatusProps> = ({
  name,
  status,
  cpuPercent,
  memoryPercent,
  restartCount,
  uptime,
}) => {
  const config = statusConfig[status] ?? statusConfig.warning;
  const StatusIcon = config.icon;

  const getMetricColor = (value: number, type: 'cpu' | 'memory') => {
    if (type === 'cpu') {
      if (value >= 80) return 'text-red-400';
      if (value >= 60) return 'text-yellow-400';
      return 'text-green-400';
    } else {
      if (value >= 85) return 'text-red-400';
      if (value >= 70) return 'text-yellow-400';
      return 'text-green-400';
    }
  };

  return (
    <div
      className={`relative overflow-hidden rounded-lg border ${config.borderColor} bg-gray-900/50 backdrop-blur-sm transition-all hover:bg-gray-900/70`}
    >
      <div className="p-6">
        {/* Header */}
        <div className="mb-4 flex items-start justify-between">
          <div className="flex-1">
            <h3 className="text-lg font-semibold text-white">{name}</h3>
            {uptime && (
              <p className="mt-1 text-sm text-gray-400">Uptime: {uptime}</p>
            )}
          </div>
          <div
            className={`flex items-center gap-2 rounded-full px-3 py-1.5 ${config.bgColor} ${config.borderColor} border`}
          >
            <StatusIcon className={`h-4 w-4 ${config.color}`} />
            <span className={`text-sm font-medium ${config.color}`}>
              {config.label}
            </span>
          </div>
        </div>

        {/* Metrics Grid */}
        <div className="grid grid-cols-2 gap-4">
          {/* CPU Usage */}
          <div className="rounded-md bg-gray-800/50 p-3">
            <div className="mb-2 flex items-center gap-2">
              <Activity className="h-4 w-4 text-blue-400" />
              <span className="text-sm font-medium text-gray-300">CPU</span>
            </div>
            <div className="flex items-baseline gap-1">
              <span
                className={`text-2xl font-bold ${getMetricColor(cpuPercent, 'cpu')}`}
              >
                {cpuPercent.toFixed(1)}
              </span>
              <span className="text-sm text-gray-500">%</span>
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-gray-700">
              <div
                className={`h-full transition-all duration-300 ${
                  cpuPercent >= 80
                    ? 'bg-red-500'
                    : cpuPercent >= 60
                      ? 'bg-yellow-500'
                      : 'bg-green-500'
                }`}
                style={{ width: `${Math.min(cpuPercent, 100)}%` }}
              />
            </div>
          </div>

          {/* Memory Usage */}
          <div className="rounded-md bg-gray-800/50 p-3">
            <div className="mb-2 flex items-center gap-2">
              <Activity className="h-4 w-4 text-purple-400" />
              <span className="text-sm font-medium text-gray-300">Memory</span>
            </div>
            <div className="flex items-baseline gap-1">
              <span
                className={`text-2xl font-bold ${getMetricColor(memoryPercent, 'memory')}`}
              >
                {memoryPercent.toFixed(1)}
              </span>
              <span className="text-sm text-gray-500">%</span>
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-gray-700">
              <div
                className={`h-full transition-all duration-300 ${
                  memoryPercent >= 85
                    ? 'bg-red-500'
                    : memoryPercent >= 70
                      ? 'bg-yellow-500'
                      : 'bg-green-500'
                }`}
                style={{ width: `${Math.min(memoryPercent, 100)}%` }}
              />
            </div>
          </div>
        </div>

        {/* Restart Count */}
        <div className="mt-4 flex items-center justify-between rounded-md bg-gray-800/30 px-4 py-2">
          <div className="flex items-center gap-2">
            <RefreshCw className="h-4 w-4 text-gray-400" />
            <span className="text-sm text-gray-400">Restarts</span>
          </div>
          <span
            className={`text-sm font-semibold ${
              restartCount > 5
                ? 'text-red-400'
                : restartCount > 2
                  ? 'text-yellow-400'
                  : 'text-gray-300'
            }`}
          >
            {restartCount}
          </span>
        </div>
      </div>

      {/* Animated border gradient */}
      <div
        className={`absolute inset-0 -z-10 rounded-lg opacity-20 blur-xl ${config.bgColor}`}
      />
    </div>
  );
};
