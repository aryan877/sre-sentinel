import React, { useEffect, useRef, useState } from 'react';
import { Terminal, Download, Trash2, Pause, Play } from 'lucide-react';

export interface LogEntry {
  id: string;
  timestamp: string;
  level: 'info' | 'warn' | 'error' | 'debug';
  message: string;
  source?: string;
}

export interface LogViewerProps {
  logs: LogEntry[];
  maxLines?: number;
  autoScroll?: boolean;
  title?: string;
  onClear?: () => void;
}

const levelConfig = {
  info: {
    color: 'text-blue-400',
    bg: 'bg-blue-500/10',
    label: 'INFO',
  },
  warn: {
    color: 'text-yellow-400',
    bg: 'bg-yellow-500/10',
    label: 'WARN',
  },
  error: {
    color: 'text-red-400',
    bg: 'bg-red-500/10',
    label: 'ERROR',
  },
  debug: {
    color: 'text-neutral-400',
    bg: 'bg-neutral-500/10',
    label: 'DEBUG',
  },
};

export const LogViewer: React.FC<LogViewerProps> = ({
  logs,
  maxLines = 100,
  autoScroll: initialAutoScroll = true,
  title = 'Container Logs',
  onClear,
}) => {
  const [autoScroll, setAutoScroll] = useState(initialAutoScroll);
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  // Limit logs to maxLines
  const displayedLogs = logs.slice(-maxLines);

  const handleDownload = () => {
    const logText = displayedLogs
      .map(
        (log) =>
          `[${log.timestamp}] [${log.level.toUpperCase()}]${log.source ? ` [${log.source}]` : ''} ${log.message}`
      )
      .join('\n');

    const blob = new Blob([logText], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `logs-${new Date().toISOString()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleScroll = () => {
    if (!containerRef.current) return;

    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    const isAtBottom = Math.abs(scrollHeight - scrollTop - clientHeight) < 10;

    if (!isAtBottom && autoScroll) {
      setAutoScroll(false);
    } else if (isAtBottom && !autoScroll) {
      setAutoScroll(true);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-[#3e3e42] bg-[#252526]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#3e3e42] px-5 py-3">
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-neutral-400" />
          <h3 className="font-semibold text-white text-base">{title}</h3>
          <span className="rounded bg-neutral-800 px-2 py-0.5 text-xs text-neutral-400">
            {displayedLogs.length} lines
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`rounded-md p-1.5 transition-colors ${
              autoScroll
                ? 'bg-green-500/10 text-green-500 hover:bg-green-500/20'
                : 'bg-neutral-800 text-neutral-400 hover:bg-neutral-700'
            }`}
            title={autoScroll ? 'Pause auto-scroll' : 'Resume auto-scroll'}
          >
            {autoScroll ? (
              <Play className="h-3.5 w-3.5" />
            ) : (
              <Pause className="h-3.5 w-3.5" />
            )}
          </button>

          <button
            onClick={handleDownload}
            className="rounded-md bg-neutral-800 p-1.5 text-neutral-400 transition-colors hover:bg-neutral-700 hover:text-white"
            title="Download logs"
          >
            <Download className="h-3.5 w-3.5" />
          </button>

          {onClear && (
            <button
              onClick={onClear}
              className="rounded-md bg-neutral-800 p-1.5 text-neutral-400 transition-colors hover:bg-red-500/10 hover:text-red-500"
              title="Clear logs"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Log Content */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto overflow-x-hidden bg-[#1e1e1e] p-4 font-mono text-xs"
        style={{ scrollBehavior: 'smooth' }}
      >
        {displayedLogs.length === 0 ? (
          <div className="flex h-full items-center justify-center text-neutral-600">
            <p className="text-sm">No logs available</p>
          </div>
        ) : (
          <div className="space-y-0.5">
            {displayedLogs.map((log) => {
              const config = levelConfig[log.level];
              return (
                <div
                  key={log.id}
                  className="group flex gap-2 rounded px-2 py-1 hover:bg-neutral-900/50"
                >
                  <span className="shrink-0 text-neutral-600">
                    {log.timestamp}
                  </span>
                  <span
                    className={`shrink-0 rounded px-1.5 text-xs font-medium ${config.bg} ${config.color}`}
                  >
                    {config.label}
                  </span>
                  {log.source && (
                    <span className="shrink-0 text-neutral-700">
                      [{log.source}]
                    </span>
                  )}
                  <span
                    className={`break-all ${
                      log.level === 'error'
                        ? 'text-red-400'
                        : log.level === 'warn'
                          ? 'text-yellow-400'
                          : 'text-neutral-400'
                    }`}
                  >
                    {log.message}
                  </span>
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-[#3e3e42] bg-[#1e1e1e] px-4 py-2">
        <div className="flex items-center justify-between text-xs text-neutral-500">
          <span>
            Showing last {maxLines} lines
            {displayedLogs.length === maxLines && ' (truncated)'}
          </span>
          {autoScroll && (
            <span className="flex items-center gap-1 text-green-500">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-green-500" />
              Auto-scrolling
            </span>
          )}
        </div>
      </div>
    </div>
  );
};