import type { DateRangePreset, DailyUsageItem } from "./types";

export const DATE_RANGE_LABELS: Record<DateRangePreset, string> = {
  today: "Today",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  "90d": "Last 90 days",
  all: "All time",
};

export function formatLocalDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function getDateRangeParams(preset: DateRangePreset): { from_date?: string; to_date?: string } {
  if (preset === "all") return {};
  const now = new Date();
  const to_date = formatLocalDate(now);
  let from_date: string;
  switch (preset) {
    case "today":
      from_date = to_date;
      break;
    case "7d":
      from_date = formatLocalDate(new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000));
      break;
    case "30d":
      from_date = formatLocalDate(new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000));
      break;
    case "90d":
      from_date = formatLocalDate(new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000));
      break;
    default:
      return {};
  }
  return { from_date, to_date };
}

export function formatCost(cost: number): string {
  if (cost === 0) return "$0.00";
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(2)}`;
}

export function formatLatency(ms: number | null): string {
  if (ms === null) return "-";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function formatDate(dateStr: string | null): string {
  if (!dateStr) return "-";
  try {
    // If the ISO string has no timezone indicator, treat as UTC
    // (backend always normalizes to UTC but serialization may omit the offset)
    let normalized = dateStr;
    if (!dateStr.endsWith("Z") && !dateStr.includes("+") && !/[-]\d{2}:\d{2}$/.test(dateStr)) {
      normalized = dateStr + "Z";
    }
    return new Date(normalized).toLocaleString();
  } catch {
    return dateStr;
  }
}

export function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
  return tokens.toString();
}

export function calculateTrend(
  data: DailyUsageItem[] | undefined,
  key: keyof DailyUsageItem,
): { value: number; direction: "up" | "down" | "neutral" } {
  if (!data || data.length < 2) return { value: 0, direction: "neutral" };
  const recent = data.slice(-7);
  const older = data.slice(-14, -7);
  if (recent.length === 0 || older.length === 0) return { value: 0, direction: "neutral" };
  const recentAvg = recent.reduce((sum, d) => sum + (Number(d[key]) || 0), 0) / recent.length;
  const olderAvg = older.reduce((sum, d) => sum + (Number(d[key]) || 0), 0) / older.length;
  if (olderAvg === 0) return { value: 0, direction: "neutral" };
  const change = ((recentAvg - olderAvg) / olderAvg) * 100;
  return {
    value: Math.abs(change),
    direction: change > 5 ? "up" : change < -5 ? "down" : "neutral",
  };
}

export function getUserTimezoneOffset(): number {
  return -new Date().getTimezoneOffset();
}

export function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return "Never";
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);
  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}
