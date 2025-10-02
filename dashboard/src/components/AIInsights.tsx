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
  low: { color: 'text-gray-400', bg: 'bg-gray-500/10' },
  medium: { color: 'text-yellow-400', bg: 'bg-yellow-500/10' },
  high: { color: 'text-red-400', bg: 'bg-red-500/10' },
};

export const AIInsights: React.FC<AIInsightsProps> = ({ insight, loading }) => {
  if (loading) {
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center rounded-lg border border-gray-700 bg-gray-900/50 backdrop-blur-sm">
        <div className="text-center">
          <div className="mb-4 inline-flex items-center justify-center">
            <Brain className="h-12 w-12 animate-pulse text-purple-400" />
          </div>
          <p className="text-lg font-medium text-gray-300">
            AI is analyzing incident...
          </p>
          <p className="mt-2 text-sm text-gray-500">
            This may take a few moments
          </p>
        </div>
      </div>
    );
  }

  if (!insight) {
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center rounded-lg border border-gray-700 bg-gray-900/50 backdrop-blur-sm">
        <div className="text-center">
          <Sparkles className="mx-auto mb-4 h-12 w-12 text-gray-600" />
          <p className="text-lg font-medium text-gray-400">
            No incidents detected
          </p>
          <p className="mt-2 text-sm text-gray-500">
            AI insights will appear here when issues are found
          </p>
        </div>
      </div>
    );
  }

  const severityStyle = severityConfig[insight.severity];

  return (
    <div className="overflow-hidden rounded-lg border border-gray-700 bg-gray-900/50 backdrop-blur-sm">
      {/* Header */}
      <div className="border-b border-gray-700 bg-gradient-to-r from-purple-900/20 to-blue-900/20 p-6">
        <div className="mb-4 flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-purple-500/20 p-2">
              <Sparkles className="h-6 w-6 text-purple-400" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white">AI Analysis</h2>
              <p className="mt-1 text-sm text-gray-400">
                Incident detected at {insight.timestamp}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div
              className={`rounded-full px-3 py-1 ${severityStyle.bg} ${severityStyle.border} border`}
            >
              <span className={`text-sm font-medium ${severityStyle.color}`}>
                {severityStyle.label} Severity
              </span>
            </div>
          </div>
        </div>

        {/* Confidence Score */}
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-gray-400" />
          <span className="text-sm text-gray-400">Confidence Score:</span>
          <div className="flex-1 max-w-xs">
            <div className="h-2 overflow-hidden rounded-full bg-gray-700">
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
          <span className="text-sm font-semibold text-white">
            {insight.confidence}%
          </span>
        </div>
      </div>

      <div className="p-6">
        <div className="space-y-6">
          {/* Root Cause */}
          <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4">
            <div className="mb-3 flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-red-400" />
              <h3 className="font-semibold text-white">Root Cause</h3>
            </div>
            <p className="text-gray-300">{insight.rootCause}</p>
          </div>

          {/* Explanation */}
          <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 p-4">
            <div className="mb-3 flex items-center gap-2">
              <Brain className="h-5 w-5 text-blue-400" />
              <h3 className="font-semibold text-white">Explanation</h3>
            </div>
            <p className="leading-relaxed text-gray-300">
              {insight.explanation}
            </p>
          </div>

          {/* Affected Components */}
          <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/5 p-4">
            <div className="mb-3 flex items-center gap-2">
              <Target className="h-5 w-5 text-yellow-400" />
              <h3 className="font-semibold text-white">Affected Components</h3>
            </div>
            <div className="flex flex-wrap gap-2">
              {insight.affectedComponents.map((component, index) => (
                <span
                  key={index}
                  className="rounded-md bg-yellow-500/10 px-3 py-1 text-sm font-medium text-yellow-300 border border-yellow-500/20"
                >
                  {component}
                </span>
              ))}
            </div>
          </div>

          {/* Suggested Fixes */}
          <div className="rounded-lg border border-green-500/20 bg-green-500/5 p-4">
            <div className="mb-4 flex items-center gap-2">
              <Wrench className="h-5 w-5 text-green-400" />
              <h3 className="font-semibold text-white">Suggested Fixes</h3>
            </div>
            <div className="space-y-3">
              {insight.suggestedFixes.map((fix, index) => {
                const priorityStyle = priorityConfig[fix.priority];
                return (
                  <div
                    key={index}
                    className="rounded-lg border border-gray-700 bg-gray-800/50 p-4 transition-all hover:border-gray-600 hover:bg-gray-800"
                  >
                    <div className="mb-2 flex items-start justify-between">
                      <h4 className="font-medium text-white">{fix.title}</h4>
                      <div className="flex items-center gap-2">
                        {fix.estimatedTime && (
                          <span className="flex items-center gap-1 text-xs text-gray-400">
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
                    <p className="text-sm text-gray-400">{fix.description}</p>
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