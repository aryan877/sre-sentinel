import React from 'react';
import {
  Sparkles,
  AlertTriangle,
  Target,
  Wrench,
  Brain,
  TrendingUp,
  Clock,
} from 'lucide-react';

export interface AIInsight {
  id: string;
  timestamp: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  rootCause: string;
  explanation: string;
  affectedComponents: string[];
  suggestedFixes: Array<{
    title: string;
    description: string;
    priority: 'low' | 'medium' | 'high';
    estimatedTime?: string;
  }>;
  confidence: number;
}

export interface AIInsightsProps {
  insight: AIInsight | null;
  loading?: boolean;
}

const severityConfig = {
  low: {
    color: 'text-blue-400',
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/20',
    label: 'Low',
  },
  medium: {
    color: 'text-yellow-400',
    bg: 'bg-yellow-500/10',
    border: 'border-yellow-500/20',
    label: 'Medium',
  },
  high: {
    color: 'text-orange-400',
    bg: 'bg-orange-500/10',
    border: 'border-orange-500/20',
    label: 'High',
  },
  critical: {
    color: 'text-red-400',
    bg: 'bg-red-500/10',
    border: 'border-red-500/20',
    label: 'Critical',
  },
};

const priorityConfig = {
  low: { color: 'text-neutral-400', bg: 'bg-neutral-500/10' },
  medium: { color: 'text-yellow-400', bg: 'bg-yellow-500/10' },
  high: { color: 'text-red-400', bg: 'bg-red-500/10' },
};

export const AIInsights: React.FC<AIInsightsProps> = ({ insight, loading }) => {
  if (loading) {
    return (
      <div className="flex h-full min-h-[350px] items-center justify-center rounded-lg border border-[#3e3e42] bg-[#252526]">
        <div className="text-center">
          <div className="mb-4 inline-flex items-center justify-center">
            <Brain className="h-8 w-8 animate-pulse text-purple-500" />
          </div>
          <p className="text-base font-medium text-white">
            AI is analyzing incident...
          </p>
          <p className="mt-2 text-sm text-neutral-500">
            This may take a few moments
          </p>
        </div>
      </div>
    );
  }

  if (!insight) {
    return (
      <div className="flex h-full min-h-[350px] items-center justify-center rounded-lg border border-[#3e3e42] bg-[#252526]">
        <div className="text-center">
          <Sparkles className="mx-auto mb-4 h-8 w-8 text-neutral-700" />
          <p className="text-base font-medium text-neutral-400">
            No incidents detected
          </p>
          <p className="mt-2 text-sm text-neutral-600">
            AI insights will appear here when issues are found
          </p>
        </div>
      </div>
    );
  }

  const severityStyle = severityConfig[insight.severity];

  return (
    <div className="overflow-hidden rounded-lg border border-[#3e3e42] bg-[#252526]">
      {/* Header */}
      <div className="border-b border-[#3e3e42] p-5">
        <div className="mb-4 flex items-start justify-between">
          <div className="flex items-center gap-3">
            <Sparkles className="h-5 w-5 text-purple-500" />
            <div>
              <h2 className="text-lg font-semibold text-white">AI Analysis</h2>
              <p className="mt-1 text-xs text-neutral-500">
                Incident detected at {insight.timestamp}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div
              className={`rounded px-2 py-1 ${severityStyle.bg}`}
            >
              <span className={`text-xs font-medium ${severityStyle.color}`}>
                {severityStyle.label} Severity
              </span>
            </div>
          </div>
        </div>

        {/* Confidence Score */}
        <div className="flex items-center gap-2">
          <TrendingUp className="h-3.5 w-3.5 text-neutral-500" />
          <span className="text-xs text-neutral-500">Confidence Score:</span>
          <div className="flex-1 max-w-xs">
            <div className="h-1.5 overflow-hidden rounded-full bg-neutral-800">
              <div
                className={`h-full transition-all ${
                  insight.confidence >= 80
                    ? 'bg-green-500'
                    : insight.confidence >= 60
                      ? 'bg-yellow-500'
                      : 'bg-red-500'
                }`}
                style={{ width: `${insight.confidence}%` }}
              />
            </div>
          </div>
          <span className="text-xs font-semibold text-white">
            {insight.confidence}%
          </span>
        </div>
      </div>

      <div className="p-5">
        <div className="space-y-4">
          {/* Root Cause */}
          <div className="rounded-lg border border-[#3e3e42] bg-[#1e1e1e] p-4">
            <div className="mb-2 flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-red-500" />
              <h3 className="font-semibold text-white text-sm">Root Cause</h3>
            </div>
            <p className="text-neutral-400 text-sm">{insight.rootCause}</p>
          </div>

          {/* Explanation */}
          <div className="rounded-lg border border-[#3e3e42] bg-[#1e1e1e] p-4">
            <div className="mb-2 flex items-center gap-2">
              <Brain className="h-4 w-4 text-blue-500" />
              <h3 className="font-semibold text-white text-sm">Explanation</h3>
            </div>
            <p className="leading-relaxed text-neutral-400 text-sm">
              {insight.explanation}
            </p>
          </div>

          {/* Affected Components */}
          <div className="rounded-lg border border-[#3e3e42] bg-[#1e1e1e] p-4">
            <div className="mb-3 flex items-center gap-2">
              <Target className="h-4 w-4 text-yellow-500" />
              <h3 className="font-semibold text-white text-sm">Affected Components</h3>
            </div>
            <div className="flex flex-wrap gap-2">
              {insight.affectedComponents.map((component, index) => (
                <span
                  key={index}
                  className="rounded bg-yellow-500/10 px-2.5 py-1 text-xs font-medium text-yellow-400 border border-yellow-500/20"
                >
                  {component}
                </span>
              ))}
            </div>
          </div>

          {/* Suggested Fixes */}
          <div className="rounded-lg border border-[#3e3e42] bg-[#1e1e1e] p-4">
            <div className="mb-3 flex items-center gap-2">
              <Wrench className="h-4 w-4 text-green-500" />
              <h3 className="font-semibold text-white text-sm">Suggested Fixes</h3>
            </div>
            <div className="space-y-2">
              {insight.suggestedFixes.map((fix, index) => {
                const priorityStyle = priorityConfig[fix.priority];
                return (
                  <div
                    key={index}
                    className="rounded-lg border border-[#3e3e42] bg-[#252526] p-3 transition-all hover:border-neutral-600"
                  >
                    <div className="mb-2 flex items-start justify-between">
                      <h4 className="font-medium text-white text-sm">{fix.title}</h4>
                      <div className="flex items-center gap-2">
                        {fix.estimatedTime && (
                          <span className="flex items-center gap-1 text-xs text-neutral-500">
                            <Clock className="h-3 w-3" />
                            {fix.estimatedTime}
                          </span>
                        )}
                        <span
                          className={`rounded px-2 py-0.5 text-xs font-medium ${priorityStyle.bg} ${priorityStyle.color}`}
                        >
                          {fix.priority}
                        </span>
                      </div>
                    </div>
                    <p className="text-xs text-neutral-500">{fix.description}</p>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};