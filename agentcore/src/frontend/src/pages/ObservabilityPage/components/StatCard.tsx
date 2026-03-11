import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ResponsiveContainer, AreaChart, Area } from "recharts";
import { ArrowUpRight, ArrowDownRight, AlertCircle } from "lucide-react";
import { THEME } from "../theme";

function Sparkline({ data, dataKey, color = THEME.primary, height = 40 }: {
  data: any[];
  dataKey: string;
  color?: string;
  height?: number;
}) {
  if (!data || data.length === 0) return null;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`sparkGradient-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.3} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} fill={`url(#sparkGradient-${dataKey})`} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function TrendIndicator({ trend }: { trend: { value: number; direction: "up" | "down" | "neutral" } }) {
  if (trend.direction === "neutral") return null;
  const isUp = trend.direction === "up";
  const color = isUp ? THEME.success : THEME.error;
  const Icon = isUp ? ArrowUpRight : ArrowDownRight;
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium" style={{ color }}>
      <Icon className="h-3 w-3" />
      <span>{trend.value.toFixed(1)}%</span>
    </span>
  );
}

export function EnhancedStatCard({
  title, value, subtitle, icon: Icon, trend, sparklineData, sparklineKey, accentColor = THEME.primary,
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: React.ElementType;
  trend?: { value: number; direction: "up" | "down" | "neutral" };
  sparklineData?: any[];
  sparklineKey?: string;
  accentColor?: string;
}) {
  return (
    <Card className="relative overflow-hidden border-0 shadow-sm hover:shadow-md transition-shadow">
      <div className="absolute top-0 left-0 w-1 h-full" style={{ backgroundColor: accentColor }} />
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2 pl-5">
        <CardTitle className="text-sm font-medium" style={{ color: THEME.textSecondary }}>{title}</CardTitle>
        {Icon && (
          <div className="p-2 rounded-lg" style={{ backgroundColor: `${accentColor}10` }}>
            <Icon className="h-4 w-4" style={{ color: accentColor }} />
          </div>
        )}
      </CardHeader>
      <CardContent className="pl-5">
        <div className="flex items-end justify-between">
          <div>
            <div className="text-2xl font-bold" style={{ color: THEME.textMain }}>{value}</div>
            {subtitle && <p className="text-xs mt-1" style={{ color: THEME.textSecondary }}>{subtitle}</p>}
            {trend && <div className="mt-2"><TrendIndicator trend={trend} /></div>}
          </div>
          {sparklineData && sparklineKey && (
            <div className="w-24 h-10">
              <Sparkline data={sparklineData} dataKey={sparklineKey} color={accentColor} />
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function ProgressBar({ value, max, color = THEME.primary, showLabel = true }: {
  value: number;
  max: number;
  color?: string;
  showLabel?: boolean;
}) {
  const percentage = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="w-full">
      <div className="flex items-center gap-2">
        <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
          <div className="h-full rounded-full transition-all duration-500" style={{ width: `${Math.min(100, percentage)}%`, backgroundColor: color }} />
        </div>
        {showLabel && (
          <span className="text-xs font-medium min-w-[40px] text-right" style={{ color: THEME.textSecondary }}>
            {percentage.toFixed(0)}%
          </span>
        )}
      </div>
    </div>
  );
}

export function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div className="bg-white border shadow-lg rounded-lg p-3">
      <p className="text-sm font-medium mb-2" style={{ color: THEME.textMain }}>{label}</p>
      {payload.map((entry: any, idx: number) => (
        <div key={idx} className="flex items-center gap-2 text-sm">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: entry.color }} />
          <span style={{ color: THEME.textSecondary }}>{entry.name}:</span>
          <span className="font-medium" style={{ color: THEME.textMain }}>
            {typeof entry.value === "number" && entry.name?.toLowerCase().includes("cost")
              ? `$${entry.value < 0.01 ? entry.value.toFixed(4) : entry.value.toFixed(2)}`
              : typeof entry.value === "number" && entry.name?.toLowerCase().includes("token")
                ? entry.value >= 1000 ? `${(entry.value / 1000).toFixed(1)}K` : entry.value
                : entry.value}
          </span>
        </div>
      ))}
    </div>
  );
}

export function TruncationBanner({ fetchedCount, onLoadAll, isLoading }: {
  fetchedCount: number;
  onLoadAll: () => void;
  isLoading: boolean;
}) {
  return (
    <Alert className="border-amber-200 bg-amber-50">
      <AlertCircle className="h-4 w-4" style={{ color: THEME.warning }} />
      <AlertTitle className="text-sm font-medium" style={{ color: THEME.textMain }}>
        Showing data from {fetchedCount.toLocaleString()} traces (limit reached)
      </AlertTitle>
      <AlertDescription className="flex items-center justify-between">
        <span className="text-sm" style={{ color: THEME.textSecondary }}>
          There may be more traces. Narrow your date range for faster results, or load all data.
        </span>
        <Button size="sm" variant="outline" onClick={onLoadAll} disabled={isLoading} className="ml-4 shrink-0 border-amber-300 hover:bg-amber-100">
          {isLoading ? "Loading..." : "Load All Data"}
        </Button>
      </AlertDescription>
    </Alert>
  );
}
