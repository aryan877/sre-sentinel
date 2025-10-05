import React from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { TooltipProps } from "recharts";
import { Activity, TrendingUp } from "lucide-react";

export interface MetricDataPoint {
  timestamp: string;
  cpu: number;
  memory: number;
  networkRx: number;
  networkTx: number;
  diskRead: number;
  diskWrite: number;
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

const formatBytes = (bytes: number): string => {
  if (bytes === 0) return "0 B/s";
  const k = 1024;
  const sizes = ["B/s", "KB/s", "MB/s", "GB/s"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
};

const CustomTooltip: React.FC<RechartsTooltipProps> = ({
  active,
  payload,
  label,
}) => {
  if (active && payload && payload.length) {
    return (
      <div className="rounded-md border border-[#3e3e42] bg-[#1e1e1e] p-3 shadow-xl">
        <p className="mb-2 text-xs font-medium text-neutral-400">{label}</p>
        {payload.map((entry, index) => (
          <div key={index} className="flex items-center gap-2">
            <div
              className="h-1.5 w-1.5 rounded-full"
              style={{ backgroundColor: entry.color }}
            />
            <span className="text-xs text-neutral-500">{entry.name}:</span>
            <span className="font-semibold text-white text-xs">
              {typeof entry.value === "number"
                ? entry.name?.includes("CPU") || entry.name?.includes("Memory")
                  ? `${entry.value.toFixed(1)}%`
                  : formatBytes(entry.value)
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
  timeRange = "Last 30 minutes",
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
  const avgNetworkRx =
    data.length > 0
      ? data.reduce((sum, point) => sum + point.networkRx, 0) / data.length
      : 0;
  const avgNetworkTx =
    data.length > 0
      ? data.reduce((sum, point) => sum + point.networkTx, 0) / data.length
      : 0;

  // Calculate max values
  const maxCpu = data.length > 0 ? Math.max(...data.map((d) => d.cpu)) : 0;
  const maxNetworkRx =
    data.length > 0 ? Math.max(...data.map((d) => d.networkRx)) : 0;
  const maxNetworkTx =
    data.length > 0 ? Math.max(...data.map((d) => d.networkTx)) : 0;

  return (
    <div className="overflow-hidden rounded-lg border border-[#3e3e42] bg-[#252526]">
      {/* Header */}
      <div className="border-b border-[#3e3e42] p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-neutral-400" />
            <div>
              <h3 className="font-semibold text-white text-base">
                {containerName
                  ? `${containerName} - Metrics`
                  : "Container Metrics"}
              </h3>
              <p className="text-xs text-neutral-500">{timeRange}</p>
            </div>
          </div>
        </div>

          {/* Summary Stats */}
          <div className="flex gap-4 flex-wrap">
            <div>
              <p className="text-xs text-neutral-500">Avg CPU</p>
              <p className="text-sm font-semibold text-white">
                {avgCpu.toFixed(1)}%
              </p>
            </div>
            <div>
              <p className="text-xs text-neutral-500">Avg Memory</p>
              <p className="text-sm font-semibold text-white">
                {avgMemory.toFixed(1)}%
              </p>
            </div>
            <div>
              <p className="text-xs text-neutral-500">Peak CPU</p>
              <p className="text-sm font-semibold text-white">
                {maxCpu.toFixed(1)}%
              </p>
            </div>
            <div>
              <p className="text-xs text-neutral-500">Avg Net RX</p>
              <p className="text-sm font-semibold text-white">
                {formatBytes(avgNetworkRx)}
              </p>
            </div>
            <div>
              <p className="text-xs text-neutral-500">Peak Net RX</p>
              <p className="text-sm font-semibold text-white">
                {formatBytes(maxNetworkRx)}
              </p>
            </div>
            <div>
              <p className="text-xs text-neutral-500">Avg Net TX</p>
              <p className="text-sm font-semibold text-white">
                {formatBytes(avgNetworkTx)}
              </p>
            </div>
            <div>
              <p className="text-xs text-neutral-500">Peak Net TX</p>
              <p className="text-sm font-semibold text-white">
                {formatBytes(maxNetworkTx)}
              </p>
            </div>
          </div>
      </div>

      {/* Chart */}
      <div className="p-5">
        {data.length === 0 ? (
          <div className="flex h-64 items-center justify-center text-neutral-500">
            <div className="text-center">
              <TrendingUp className="mx-auto mb-2 h-8 w-8 text-neutral-700" />
              <p className="text-sm">No metrics data available</p>
            </div>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <LineChart
              data={data}
              margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#1f1f1f" />
              <XAxis
                dataKey="timestamp"
                stroke="#666"
                style={{ fontSize: "11px" }}
                tickLine={false}
              />
              <YAxis
                stroke="#666"
                style={{ fontSize: "11px" }}
                tickLine={false}
                domain={[0, 100]}
                label={{
                  value: "Usage (%)",
                  angle: -90,
                  position: "insideLeft",
                  style: { fill: "#666", fontSize: "11px" },
                }}
              />
              <Tooltip content={<CustomTooltip />} />
              {showLegend && (
                <Legend
                  wrapperStyle={{
                    paddingTop: "15px",
                    fontSize: "11px",
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
                  fill: "#3B82F6",
                  stroke: "#1F2937",
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
                  fill: "#A855F7",
                  stroke: "#1F2937",
                  strokeWidth: 2,
                }}
              />
              <Line
                type="monotone"
                dataKey="networkRx"
                stroke="#10B981"
                strokeWidth={2}
                dot={false}
                name="Network RX"
                activeDot={{
                  r: 6,
                  fill: "#10B981",
                  stroke: "#1F2937",
                  strokeWidth: 2,
                }}
              />
              <Line
                type="monotone"
                dataKey="networkTx"
                stroke="#06B6D4"
                strokeWidth={2}
                dot={false}
                name="Network TX"
                activeDot={{
                  r: 6,
                  fill: "#06B6D4",
                  stroke: "#1F2937",
                  strokeWidth: 2,
                }}
              />
              <Line
                type="monotone"
                dataKey="diskRead"
                stroke="#F97316"
                strokeWidth={2}
                dot={false}
                name="Disk Read"
                activeDot={{
                  r: 6,
                  fill: "#F97316",
                  stroke: "#1F2937",
                  strokeWidth: 2,
                }}
              />
              <Line
                type="monotone"
                dataKey="diskWrite"
                stroke="#EF4444"
                strokeWidth={2}
                dot={false}
                name="Disk Write"
                activeDot={{
                  r: 6,
                  fill: "#EF4444",
                  stroke: "#1F2937",
                  strokeWidth: 2,
                }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Footer with indicators */}
      <div className="border-t border-[#3e3e42] bg-[#1e1e1e] p-3">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-1">
              <div className="h-1.5 w-1.5 rounded-full bg-blue-500" />
              <span className="text-neutral-500">CPU</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="h-1.5 w-1.5 rounded-full bg-purple-500" />
              <span className="text-neutral-500">Memory</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="h-1.5 w-1.5 rounded-full bg-green-500" />
              <span className="text-neutral-500">Net RX</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="h-1.5 w-1.5 rounded-full bg-cyan-500" />
              <span className="text-neutral-500">Net TX</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="h-1.5 w-1.5 rounded-full bg-orange-500" />
              <span className="text-neutral-500">Disk Read</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="h-1.5 w-1.5 rounded-full bg-red-500" />
              <span className="text-neutral-500">Disk Write</span>
            </div>
          </div>
          <span className="text-neutral-600">{data.length} data points</span>
        </div>
      </div>
    </div>
  );
};
