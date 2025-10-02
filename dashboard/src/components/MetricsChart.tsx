import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import type { TooltipProps } from 'recharts';
import { Activity, TrendingUp } from 'lucide-react';

export interface MetricDataPoint {
  timestamp: string;
  cpu: number;
  memory: number;
}

export interface MetricsChartProps {
  data: MetricDataPoint[];
  containerName?: string;
  timeRange?: string;
  showLegend?: boolean;
}

type RechartsTooltipProps = TooltipProps<number, string> & {
  payload?: Array<{
    color?: string;
    name?: string;
    value?: number;
  }>;
  label?: string | number;
  active?: boolean;
};

const CustomTooltip: React.FC<RechartsTooltipProps> = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-900/95 p-3 shadow-xl backdrop-blur-sm">
        <p className="mb-2 text-sm font-medium text-gray-300">{label}</p>
        {payload.map((entry, index) => (
          <div key={index} className="flex items-center gap-2">
            <div
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: entry.color }}
            />
            <span className="text-sm text-gray-400">{entry.name}:</span>
            <span className="font-semibold text-white">
              {typeof entry.value === 'number'
                ? `${entry.value.toFixed(1)}%`
                : entry.value}
            </span>
          </div>
        ))}
      </div>
    );
  }
  return null;
};

export const MetricsChart: React.FC<MetricsChartProps> = ({
  data,
  containerName,
  timeRange = 'Last 30 minutes',
  showLegend = true,
}) => {
  // Calculate average values for summary
  const avgCpu =
    data.length > 0
      ? data.reduce((sum, point) => sum + point.cpu, 0) / data.length
      : 0;
  const avgMemory =
    data.length > 0
      ? data.reduce((sum, point) => sum + point.memory, 0) / data.length
      : 0;

  // Calculate max values
  const maxCpu = data.length > 0 ? Math.max(...data.map((d) => d.cpu)) : 0;

  return (
    <div className="overflow-hidden rounded-lg border border-gray-700 bg-gray-900/50 backdrop-blur-sm">
      {/* Header */}
      <div className="border-b border-gray-700 bg-gray-800/50 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-blue-400" />
            <div>
              <h3 className="font-semibold text-white">
                {containerName ? `${containerName} - Metrics` : 'Container Metrics'}
              </h3>
              <p className="text-sm text-gray-400">{timeRange}</p>
            </div>
          </div>

          {/* Summary Stats */}
          <div className="flex gap-6">
            <div className="text-right">
              <p className="text-xs text-gray-500">Avg CPU</p>
              <p className="text-lg font-semibold text-blue-400">
                {avgCpu.toFixed(1)}%
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs text-gray-500">Avg Memory</p>
              <p className="text-lg font-semibold text-purple-400">
                {avgMemory.toFixed(1)}%
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs text-gray-500">Peak CPU</p>
              <p className="text-lg font-semibold text-red-400">
                {maxCpu.toFixed(1)}%
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Chart */}
      <div className="p-4">
        {data.length === 0 ? (
          <div className="flex h-80 items-center justify-center text-gray-500">
            <div className="text-center">
              <TrendingUp className="mx-auto mb-2 h-12 w-12 text-gray-600" />
              <p>No metrics data available</p>
            </div>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <LineChart
              data={data}
              margin={{ top: 5, right: 30, left: 0, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="timestamp"
                stroke="#9CA3AF"
                style={{ fontSize: '12px' }}
                tickLine={false}
              />
              <YAxis
                stroke="#9CA3AF"
                style={{ fontSize: '12px' }}
                tickLine={false}
                domain={[0, 100]}
                label={{
                  value: 'Usage (%)',
                  angle: -90,
                  position: 'insideLeft',
                  style: { fill: '#9CA3AF', fontSize: '12px' },
                }}
              />
              <Tooltip content={<CustomTooltip />} />
              {showLegend && (
                <Legend
                  wrapperStyle={{
                    paddingTop: '20px',
                    fontSize: '14px',
                  }}
                  iconType="line"
                />
              )}
              <Line
                type="monotone"
                dataKey="cpu"
                stroke="#3B82F6"
                strokeWidth={2}
                dot={false}
                name="CPU Usage"
                activeDot={{
                  r: 6,
                  fill: '#3B82F6',
                  stroke: '#1F2937',
                  strokeWidth: 2,
                }}
              />
              <Line
                type="monotone"
                dataKey="memory"
                stroke="#A855F7"
                strokeWidth={2}
                dot={false}
                name="Memory Usage"
                activeDot={{
                  r: 6,
                  fill: '#A855F7',
                  stroke: '#1F2937',
                  strokeWidth: 2,
                }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Footer with indicators */}
      <div className="border-t border-gray-700 bg-gray-800/50 p-3">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <div className="h-2 w-2 rounded-full bg-blue-500" />
              <span className="text-gray-400">CPU</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="h-2 w-2 rounded-full bg-purple-500" />
              <span className="text-gray-400">Memory</span>
            </div>
          </div>
          <span className="text-gray-500">{data.length} data points</span>
        </div>
      </div>
    </div>
  );
};
