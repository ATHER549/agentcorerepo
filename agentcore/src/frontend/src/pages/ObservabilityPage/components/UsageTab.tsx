import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ResponsiveContainer, BarChart, Bar, AreaChart, Area, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend,
} from "recharts";
import { Activity, Layers, Calendar, Search } from "lucide-react";
import { THEME } from "../theme";
import { formatCost, formatTokens } from "../utils";
import type { Metrics } from "../types";
import { CustomTooltip } from "./StatCard";

interface UsageTabProps {
  metrics: Metrics | undefined;
  metricsLoading: boolean;
}

export function UsageTab({ metrics, metricsLoading }: UsageTabProps) {
  const [search, setSearch] = useState("");
  const filteredUsageData = useMemo(() => {
    if (!metrics?.by_date) return [];
    if (!search.trim()) return metrics.by_date;
    const s = search.toLowerCase();
    return metrics.by_date.filter(day => day.date?.toLowerCase().includes(s));
  }, [metrics?.by_date, search]);

  if (metricsLoading) return <Skeleton className="h-64" />;

  return (
    <div className="space-y-4">
      {metrics?.by_date && metrics.by_date.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card className="border-0 shadow-sm">
            <CardHeader>
              <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                <Activity className="h-5 w-5" style={{ color: THEME.primary }} />
                Traces & Observations
              </CardTitle>
              <CardDescription style={{ color: THEME.textSecondary }}>Daily activity breakdown</CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={metrics.by_date}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="date" tick={{ fontSize: 12, fill: THEME.textSecondary }} tickFormatter={(v) => v.slice(5)} axisLine={{ stroke: '#e5e7eb' }} />
                  <YAxis tick={{ fontSize: 12, fill: THEME.textSecondary }} axisLine={{ stroke: '#e5e7eb' }} />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend />
                  <Bar dataKey="trace_count" fill={THEME.primary} name="Traces" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="observation_count" fill={THEME.chartColors[1]} name="Observations" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card className="border-0 shadow-sm">
            <CardHeader>
              <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                <Layers className="h-5 w-5" style={{ color: THEME.chartColors[2] }} />
                Token Usage Trend
              </CardTitle>
              <CardDescription style={{ color: THEME.textSecondary }}>Token breakdown over time</CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={metrics.by_date}>
                  <defs>
                    <linearGradient id="usageTokenGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={THEME.chartColors[2]} stopOpacity={0.3} />
                      <stop offset="100%" stopColor={THEME.chartColors[2]} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="date" tick={{ fontSize: 12, fill: THEME.textSecondary }} tickFormatter={(v) => v.slice(5)} axisLine={{ stroke: '#e5e7eb' }} />
                  <YAxis tick={{ fontSize: 12, fill: THEME.textSecondary }} tickFormatter={(v) => formatTokens(v)} axisLine={{ stroke: '#e5e7eb' }} />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend />
                  <Area type="monotone" dataKey="total_tokens" stroke={THEME.chartColors[2]} strokeWidth={2} fill="url(#usageTokenGradient)" name="Total Tokens" />
                </AreaChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>
      )}

      <Card className="border-0 shadow-sm">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
              <Calendar className="h-5 w-5" style={{ color: THEME.chartColors[3] }} />
              Daily Usage Details
            </CardTitle>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4" style={{ color: THEME.textSecondary }} />
              <Input placeholder="Search by date..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9 h-9 w-64 bg-gray-50 border-gray-200" />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {filteredUsageData && filteredUsageData.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow className="border-gray-100">
                  <TableHead style={{ color: THEME.textSecondary }}>Date</TableHead>
                  <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Traces</TableHead>
                  <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Observations</TableHead>
                  <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Tokens</TableHead>
                  <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredUsageData.map((day) => (
                  <TableRow key={day.date} className="border-gray-100 hover:bg-gray-50">
                    <TableCell className="font-medium" style={{ color: THEME.textMain }}>{day.date}</TableCell>
                    <TableCell className="text-right" style={{ color: THEME.textMain }}>{day.trace_count}</TableCell>
                    <TableCell className="text-right" style={{ color: THEME.textMain }}>{day.observation_count}</TableCell>
                    <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(day.total_tokens)}</TableCell>
                    <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatCost(day.total_cost)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-center py-12">
              <Calendar className="h-12 w-12 mx-auto mb-4" style={{ color: THEME.textSecondary }} />
              <p style={{ color: THEME.textSecondary }}>{search ? `No results for "${search}"` : "No usage data"}</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
