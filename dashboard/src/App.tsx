import { useCallback, useMemo, useState } from "react";
import {
  Shield,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Zap,
  Brain,
  Wrench,
} from "lucide-react";
import { ContainerStatus } from "./components/ContainerStatus";
import { LogViewer } from "./components/LogViewer";
import { AIInsights } from "./components/AIInsights";
import { MetricsChart } from "./components/MetricsChart";
import type { LogEntry } from "./components/LogViewer";
import type { MetricDataPoint } from "./components/MetricsChart";
import { useWebSocket } from "./hooks/useWebSocket";

interface Container {
  id: string;
  name: string;
  service: string;
  status: "healthy" | "warning" | "critical" | "offline";
  restarts: number;
  cpu: number;
  memory: number;
  networkRx: number;
  networkTx: number;
  diskRead: number;
  diskWrite: number;
}

interface Incident {
  id: string;
  service: string;
  detected_at: string;
  status: string;
  anomaly?: any;
  analysis?: any;
  explanation?: string;
}

function App() {
  const [containers, setContainers] = useState<Container[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [currentIncident, setCurrentIncident] = useState<Incident | null>(null);
  const [metricsHistory, setMetricsHistory] = useState<
    Record<string, MetricDataPoint[]>
  >({});

  const wsUrl = useMemo(() => {
    // First try the explicit environment variable
    const explicit = import.meta.env.VITE_WS_URL;
    if (explicit) {
      return explicit;
    }

    // In Docker, we need to connect through the proxy
    // Check if we're in production (Docker) environment
    if (
      window.location.hostname !== "localhost" &&
      window.location.hostname !== "127.0.0.1"
    ) {
      // In Docker, use the proxied WebSocket endpoint
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      return `${protocol}//${window.location.host}/ws`;
    }

    // Fallback for local development
    const origin = window.location.origin.replace(/^http/, "ws");
    return `${origin.replace(/\/?$/, "")}/ws`;
  }, []);

  const toUiStatus = useCallback(
    (status: string | undefined | null): Container["status"] => {
      const normalized = (status ?? "").toLowerCase();
      switch (normalized) {
        case "running":
        case "healthy":
          return "healthy";
        case "starting":
        case "unknown":
        case "warning":
          return "warning";
        case "offline":
        case "exited":
          return "offline";
        case "critical":
        case "unhealthy":
          return "critical";
        default:
          return "critical";
      }
    },
    []
  );

  const handleMessage = useCallback(
    (data: any) => {
      switch (data.type) {
        case "bootstrap":
          if (Array.isArray(data.containers)) {
            const initialHistory: Record<string, MetricDataPoint[]> = {};
            setContainers(
              data.containers.map((container: any) => {
                const cpuValue = Number(container.cpu ?? 0);
                const memoryValue = Number(container.memory ?? 0);
                const networkRxValue = Number(container.networkRx ?? 0);
                const networkTxValue = Number(container.networkTx ?? 0);
                const diskReadValue = Number(container.diskRead ?? 0);
                const diskWriteValue = Number(container.diskWrite ?? 0);
                const metricsSample: MetricDataPoint = {
                  timestamp: new Date().toLocaleTimeString(),
                  cpu: Number.isFinite(cpuValue) ? cpuValue : 0,
                  memory: Number.isFinite(memoryValue) ? memoryValue : 0,
                  networkRx: Number.isFinite(networkRxValue)
                    ? networkRxValue
                    : 0,
                  networkTx: Number.isFinite(networkTxValue)
                    ? networkTxValue
                    : 0,
                  diskRead: Number.isFinite(diskReadValue) ? diskReadValue : 0,
                  diskWrite: Number.isFinite(diskWriteValue)
                    ? diskWriteValue
                    : 0,
                };
                initialHistory[container.id] = [metricsSample];

                return {
                  id: container.id,
                  name: container.name,
                  service: container.service,
                  status: toUiStatus(container.status),
                  restarts: Number.isFinite(Number(container.restarts))
                    ? Number(container.restarts)
                    : 0,
                  cpu: container.cpu ?? 0,
                  memory: container.memory ?? 0,
                  networkRx: container.networkRx ?? 0,
                  networkTx: container.networkTx ?? 0,
                  diskRead: container.diskRead ?? 0,
                  diskWrite: container.diskWrite ?? 0,
                } satisfies Container;
              })
            );
            setMetricsHistory(initialHistory);
          }
          if (Array.isArray(data.incidents)) {
            setIncidents(data.incidents);
            if (data.incidents.length > 0) {
              setCurrentIncident(data.incidents[data.incidents.length - 1]);
            }
          }
          break;
        case "container_update":
          setContainers((prev) => {
            const next = [...prev];
            const idx = next.findIndex((c) => c.id === data.container.id);
            const restartsValue = Number(data.container.restarts);
            const updated = {
              id: data.container.id,
              name: data.container.name,
              service: data.container.service,
              status: toUiStatus(data.container.status),
              restarts: Number.isFinite(restartsValue) ? restartsValue : 0,
              cpu: data.container.cpu ?? 0,
              memory: data.container.memory ?? 0,
              networkRx: data.container.networkRx ?? 0,
              networkTx: data.container.networkTx ?? 0,
              diskRead: data.container.diskRead ?? 0,
              diskWrite: data.container.diskWrite ?? 0,
            } satisfies Container;
            if (idx >= 0) {
              next[idx] = { ...next[idx], ...updated };
            } else {
              next.push(updated);
            }
            return next;
          });
          {
            const timestampIso =
              typeof data.container.timestamp === "string"
                ? data.container.timestamp
                : new Date().toISOString();
            const cpuValue = Number(data.container.cpu ?? 0);
            const memoryValue = Number(data.container.memory ?? 0);
            const networkRxValue = Number(data.container.networkRx ?? 0);
            const networkTxValue = Number(data.container.networkTx ?? 0);
            const diskReadValue = Number(data.container.diskRead ?? 0);
            const diskWriteValue = Number(data.container.diskWrite ?? 0);
            const sample: MetricDataPoint = {
              timestamp: new Date(timestampIso).toLocaleTimeString(),
              cpu: Number.isFinite(cpuValue) ? cpuValue : 0,
              memory: Number.isFinite(memoryValue) ? memoryValue : 0,
              networkRx: Number.isFinite(networkRxValue) ? networkRxValue : 0,
              networkTx: Number.isFinite(networkTxValue) ? networkTxValue : 0,
              diskRead: Number.isFinite(diskReadValue) ? diskReadValue : 0,
              diskWrite: Number.isFinite(diskWriteValue) ? diskWriteValue : 0,
            };
            setMetricsHistory((prev) => {
              const history = prev[data.container.id] ?? [];
              const trimmed = [...history.slice(-119), sample];
              return { ...prev, [data.container.id]: trimmed };
            });
          }
          break;
        case "log":
          if (typeof data.message === "string") {
            const timestampIso =
              typeof data.timestamp === "string"
                ? data.timestamp
                : new Date().toISOString();
            const levelRaw =
              typeof data.level === "string"
                ? data.level.toLowerCase()
                : "info";
            const level: LogEntry["level"] = [
              "info",
              "warn",
              "error",
              "debug",
            ].includes(levelRaw)
              ? (levelRaw as LogEntry["level"])
              : "info";
            const entry: LogEntry = {
              id: `${timestampIso}-${Math.random().toString(36).slice(2, 8)}`,
              timestamp: new Date(timestampIso).toLocaleTimeString(),
              level,
              message: data.message,
              source: data.container ?? data.service ?? "system",
            };
            setLogs((prev) => [...prev.slice(-99), entry]);
          }
          break;
        case "incident":
          if (data.incident) {
            setIncidents((prev) => [...prev, data.incident]);
            setCurrentIncident(data.incident);
          }
          break;
        case "incident_update":
          if (data.incident) {
            setIncidents((prev) => {
              const existing = prev.findIndex((i) => i.id === data.incident.id);
              if (existing === -1) {
                return [...prev, data.incident];
              }
              const copy = [...prev];
              copy[existing] = data.incident;
              return copy;
            });
            setCurrentIncident(data.incident);
          }
          break;
        default:
          break;
      }
    },
    [toUiStatus]
  );

  const { connected } = useWebSocket({ url: wsUrl, onMessage: handleMessage });

  const healthyCount = containers.filter((c) => c.status === "healthy").length;
  const criticalCount = containers.filter(
    (c) => c.status === "critical"
  ).length;

  const primaryContainer = containers[0] ?? null;
  const primaryContainerId = primaryContainer?.id;
  const primaryMetrics = useMemo<MetricDataPoint[]>(() => {
    if (!primaryContainerId) return [];
    return metricsHistory[primaryContainerId] ?? [];
  }, [primaryContainerId, metricsHistory]);

  const currentInsight = useMemo(() => {
    if (!currentIncident?.analysis) return null;
    const analysis = currentIncident.analysis;
    const severity = currentIncident.anomaly?.severity ?? "medium";

    return {
      id: currentIncident.id,
      timestamp: currentIncident.detected_at,
      severity,
      rootCause: analysis.root_cause ?? "Unknown root cause",
      explanation: analysis.explanation ?? "",
      affectedComponents: analysis.affected_components ?? [],
      suggestedFixes: (analysis.suggested_fixes ?? []).map((fix: any) => ({
        title: fix.action ?? "action",
        description: fix.details ?? "",
        priority:
          (fix.priority ?? 1) <= 2
            ? "high"
            : (fix.priority ?? 1) <= 4
            ? "medium"
            : "low",
        estimatedTime: undefined,
      })),
      confidence: Math.round((analysis.confidence ?? 0) * 100),
    };
  }, [currentIncident]);

  return (
    <div className="min-h-screen bg-black text-white">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-gray-800 bg-black">
        <div className="flex items-center justify-between max-w-[1400px] mx-auto px-6 py-4">
          <div className="flex items-center gap-3">
            <Shield className="w-6 h-6 text-white" />
            <h1 className="text-xl font-semibold">SRE Sentinel</h1>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-sm">
              <div
                className={`w-1.5 h-1.5 rounded-full ${
                  connected ? "bg-green-500" : "bg-red-500"
                }`}
              />
              <span className="text-gray-400">
                {connected ? "Connected" : "Disconnected"}
              </span>
            </div>

            <div className="flex items-center gap-4 text-sm">
              <div className="flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 text-green-500" />
                <span className="text-gray-400">{healthyCount}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 text-red-500" />
                <span className="text-gray-400">{criticalCount}</span>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-[1400px] mx-auto px-6 py-8">
        {/* Tech Stack Banner */}
        <div className="mb-8 border border-gray-800 rounded-lg bg-[#0a0a0a] p-5">
          <div className="flex items-center justify-around text-sm">
            <div className="flex items-center gap-3">
              <Zap className="w-4 h-4 text-yellow-500" />
              <div>
                <p className="text-gray-500 text-xs">Fast Detection</p>
                <p className="font-medium text-white">Cerebras 2.6K tok/s</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Brain className="w-4 h-4 text-purple-500" />
              <div>
                <p className="text-gray-500 text-xs">Deep Analysis</p>
                <p className="font-medium text-white">Llama 4 (10M context)</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Wrench className="w-4 h-4 text-cyan-500" />
              <div>
                <p className="text-gray-500 text-xs">Secure Orchestration</p>
                <p className="font-medium text-white">Docker MCP Gateway</p>
              </div>
            </div>
          </div>
        </div>

        {/* Container Status Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4 mb-8">
          {containers.map((container) => (
            <ContainerStatus
              key={container.id}
              name={container.service || container.name}
              status={container.status}
              cpuPercent={container.cpu}
              memoryPercent={container.memory}
              networkRx={container.networkRx}
              networkTx={container.networkTx}
              diskRead={container.diskRead}
              diskWrite={container.diskWrite}
              restartCount={container.restarts ?? 0}
            />
          ))}
        </div>

        {/* Two Column Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
          {/* Metrics Chart */}
          <MetricsChart
            data={primaryMetrics}
            containerName={primaryContainer?.service ?? primaryContainer?.name}
            timeRange="Recent samples"
            showLegend
          />

          {/* Recent Incidents */}
          <div className="bg-[#0a0a0a] border border-gray-800 rounded-lg p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-base font-semibold flex items-center gap-2">
                <Clock className="w-4 h-4 text-gray-400" />
                Recent Incidents
              </h2>
              <span className="text-xs text-gray-500">
                {incidents.length} total
              </span>
            </div>

            <div className="space-y-2">
              {incidents.length === 0 ? (
                <p className="text-gray-500 text-center py-8 text-sm">
                  No incidents detected
                </p>
              ) : (
                incidents
                  .slice(-5)
                  .reverse()
                  .map((incident) => (
                    <div
                      key={incident.id}
                      className="p-3 bg-black rounded-md border border-gray-800 cursor-pointer hover:border-gray-700 transition-colors"
                      onClick={() => setCurrentIncident(incident)}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium text-sm">{incident.id}</span>
                        <span
                          className={`text-xs px-2 py-0.5 rounded ${
                            incident.status === "resolved"
                              ? "bg-green-500/10 text-green-500"
                              : incident.status === "analyzing"
                              ? "bg-yellow-500/10 text-yellow-500"
                              : "bg-red-500/10 text-red-500"
                          }`}
                        >
                          {incident.status}
                        </span>
                      </div>
                      <p className="text-sm text-gray-400">
                        {incident.service}
                      </p>
                      <p className="text-xs text-gray-600 mt-1">
                        {new Date(incident.detected_at).toLocaleString()}
                      </p>
                    </div>
                  ))
              )}
            </div>
          </div>
        </div>

        {/* AI Insights */}
        <div className="mb-8">
          <AIInsights
            insight={currentInsight}
            loading={currentIncident?.analysis == null && currentIncident != null}
          />
        </div>

        {/* Log Viewer */}
        <LogViewer
          logs={logs}
          onClear={() => setLogs([])}
          title={
            primaryContainer
              ? `${primaryContainer.service ?? primaryContainer.name} Logs`
              : "Container Logs"
          }
        />
      </main>
    </div>
  );
}

export default App;
