import { useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Area, AreaChart, PieChart, Pie, Cell, Legend, ComposedChart,
} from "recharts";
import {
  Activity, Layers, DollarSign, Clock, TrendingUp, Timer, Cpu,
  PieChart as PieChartIcon, ChevronRight, XCircle,
} from "lucide-react";
import { THEME } from "../theme";
import { formatCost, formatTokens, formatLatency, calculateTrend, formatRelativeTime } from "../utils";
import type { Metrics, AgentListItem, SessionListItem, AgentsResponse, SessionsResponse } from "../types";
import { EnhancedStatCard, ProgressBar, CustomTooltip, TruncationBanner } from "./StatCard";

interface OverviewTabProps {
  metrics: Metrics | undefined;
  metricsLoading: boolean;
  agentsData: AgentsResponse | undefined;
  sessionsData: SessionsResponse | undefined;
  fetchAllMode: boolean;
  onLoadAll: () => void;
  onSelectSession: (id: string) => void;
}

export function OverviewTab({
  metrics, metricsLoading, agentsData, sessionsData,
  fetchAllMode, onLoadAll, onSelectSession,
}: OverviewTabProps) {
  const tokensTrend = useMemo(() => calculateTrend(metrics?.by_date, "total_tokens"), [metrics?.by_date]);
  const costTrend = useMemo(() => calculateTrend(metrics?.by_date, "total_cost"), [metrics?.by_date]);
  const tracesTrend = useMemo(() => calculateTrend(metrics?.by_date, "trace_count"), [metrics?.by_date]);

  const recentAgents = useMemo(() => {
    if (!agentsData?.agents) return [];
    return [...agentsData.agents]
      .filter(a => a.last_activity)
      .sort((a, b) => new Date(b.last_activity || 0).getTime() - new Date(a.last_activity || 0).getTime())
      .slice(0, 4);
  }, [agentsData]);

  return (
    <div className="space-y-6">
      {metrics?.truncated && !fetchAllMode && (
        <TruncationBanner fetchedCount={metrics.fetched_trace_count ?? 0} onLoadAll={onLoadAll} isLoading={metricsLoading} />
      )}
      {metricsLoading ? (
        <div className="grid gap-4 md:grid-cols-4">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-32" />)}
        </div>
      ) : (
        <>
          {/* KPI Cards */}
          <div className="grid gap-4 md:grid-cols-4">
            <EnhancedStatCard title="Total Traces" value={metrics?.total_traces ?? 0} icon={Activity} trend={tracesTrend} sparklineData={metrics?.by_date} sparklineKey="trace_count" accentColor={THEME.primary} />
            <EnhancedStatCard title="Total Tokens" value={formatTokens(metrics?.total_tokens ?? 0)} subtitle={`${formatTokens(metrics?.input_tokens ?? 0)} in / ${formatTokens(metrics?.output_tokens ?? 0)} out`} icon={Layers} trend={tokensTrend} sparklineData={metrics?.by_date} sparklineKey="total_tokens" accentColor={THEME.chartColors[1]} />
            <EnhancedStatCard title="Total Cost" value={formatCost(metrics?.total_cost_usd ?? 0)} icon={DollarSign} trend={costTrend} sparklineData={metrics?.by_date} sparklineKey="total_cost" accentColor={THEME.chartColors[2]} />
            <EnhancedStatCard title="Sessions" value={metrics?.total_sessions ?? 0} icon={Clock} accentColor={THEME.chartColors[3]} />
          </div>

          {/* Cost Analysis Chart */}
          {metrics?.by_date && metrics.by_date.length > 0 && (
            <Card className="border-0 shadow-sm">
              <CardHeader>
                <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                  <DollarSign className="h-5 w-5" style={{ color: THEME.chartColors[2] }} />
                  Cost Analysis
                </CardTitle>
                <CardDescription style={{ color: THEME.textSecondary }}>Daily cost trend with activity correlation</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={220}>
                  <ComposedChart data={metrics.by_date}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="date" tick={{ fontSize: 12, fill: THEME.textSecondary }} tickFormatter={(v) => v.slice(5)} axisLine={{ stroke: '#e5e7eb' }} />
                    <YAxis yAxisId="left" tick={{ fontSize: 12, fill: THEME.textSecondary }} tickFormatter={(v) => formatCost(v)} axisLine={{ stroke: '#e5e7eb' }} />
                    <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 12, fill: THEME.textSecondary }} axisLine={{ stroke: '#e5e7eb' }} />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend />
                    <Bar yAxisId="right" dataKey="trace_count" fill={THEME.chartColors[1]} opacity={0.3} radius={[4, 4, 0, 0]} name="Traces" />
                    <Line yAxisId="left" type="monotone" dataKey="total_cost" stroke={THEME.chartColors[2]} strokeWidth={2} dot={{ r: 4, fill: THEME.chartColors[2] }} activeDot={{ r: 6 }} name="Cost" />
                  </ComposedChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          {/* Agent Activity & Performance */}
          <div className="grid gap-4 md:grid-cols-2">
            {/* Recent Agent Activity */}
            <Card className="border-0 shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2" style={{ color: THEME.textSecondary }}>
                  <Activity className="h-4 w-4" />
                  Recent Agent Activity
                </CardTitle>
              </CardHeader>
              <CardContent>
                {recentAgents.length === 0 ? (
                  <div className="text-center py-4">
                    <Activity className="h-8 w-8 mx-auto mb-2 text-gray-300" />
                    <p className="text-sm" style={{ color: THEME.textSecondary }}>No recent activity</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {recentAgents.map((agent) => (
                      <div key={agent.agent_id} className="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50 transition-colors">
                        <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: agent.error_count > 0 ? THEME.error : THEME.success }} />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium truncate" style={{ color: THEME.textMain }}>{agent.agent_name || 'Unnamed Agent'}</p>
                          <p className="text-xs" style={{ color: THEME.textSecondary }}>{agent.session_count} sessions • {agent.error_count > 0 ? `${agent.error_count} errors` : 'No errors'}</p>
                        </div>
                        <div className="text-right flex-shrink-0">
                          <p className="text-xs font-medium" style={{ color: THEME.textSecondary }}>{formatRelativeTime(agent.last_activity)}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Performance */}
            <Card className="border-0 shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2" style={{ color: THEME.textSecondary }}>
                  <Timer className="h-4 w-4" />
                  Performance
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <div className="flex justify-between text-sm mb-2">
                    <span style={{ color: THEME.textSecondary }}>Avg Latency</span>
                    <span className="font-medium" style={{ color: THEME.textMain }}>{formatLatency(metrics?.avg_latency_ms ?? null)}</span>
                  </div>
                  <ProgressBar value={metrics?.avg_latency_ms ?? 0} max={10000} color={THEME.chartColors[1]} />
                </div>
                <div>
                  <div className="flex justify-between text-sm mb-2">
                    <span style={{ color: THEME.textSecondary }}>P95 Latency</span>
                    <span className="font-medium" style={{ color: THEME.textMain }}>{formatLatency(metrics?.p95_latency_ms ?? null)}</span>
                  </div>
                  <ProgressBar value={metrics?.p95_latency_ms ?? 0} max={15000} color={THEME.chartColors[3]} />
                </div>
                <div>
                  <div className="flex justify-between text-sm mb-2">
                    <span style={{ color: THEME.textSecondary }}>Observations</span>
                    <span className="font-medium" style={{ color: THEME.textMain }}>{metrics?.total_observations ?? 0}</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Charts Row */}
          <div className="grid gap-4 md:grid-cols-2">
            {metrics?.by_date && metrics.by_date.length > 0 && (
              <Card className="border-0 shadow-sm">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                    <TrendingUp className="h-5 w-5" style={{ color: THEME.primary }} />
                    Token Usage Trend
                  </CardTitle>
                  <CardDescription style={{ color: THEME.textSecondary }}>Daily token consumption over time</CardDescription>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={280}>
                    <AreaChart data={metrics.by_date}>
                      <defs>
                        <linearGradient id="tokenGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={THEME.primary} stopOpacity={0.3} />
                          <stop offset="100%" stopColor={THEME.primary} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis dataKey="date" tick={{ fontSize: 12, fill: THEME.textSecondary }} tickFormatter={(v) => v.slice(5)} axisLine={{ stroke: '#e5e7eb' }} />
                      <YAxis tick={{ fontSize: 12, fill: THEME.textSecondary }} tickFormatter={(v) => formatTokens(v)} axisLine={{ stroke: '#e5e7eb' }} />
                      <Tooltip content={<CustomTooltip />} />
                      <Area type="monotone" dataKey="total_tokens" stroke={THEME.primary} strokeWidth={2} fill="url(#tokenGradient)" name="Tokens" />
                    </AreaChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}

            {metrics?.by_model && metrics.by_model.length > 0 && (
              <Card className="border-0 shadow-sm">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                    <PieChartIcon className="h-5 w-5" style={{ color: THEME.chartColors[1] }} />
                    Model Distribution
                  </CardTitle>
                  <CardDescription style={{ color: THEME.textSecondary }}>Token usage breakdown by model</CardDescription>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={280}>
                    <PieChart>
                      <Pie data={metrics.by_model.slice(0, 5)} cx="50%" cy="50%" innerRadius={70} outerRadius={100} paddingAngle={3} dataKey="total_tokens" nameKey="model">
                        {metrics.by_model.slice(0, 5).map((_, index) => (
                          <Cell key={`cell-${index}`} fill={THEME.chartColors[index % THEME.chartColors.length]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={((value: number | string) => formatTokens(Number(value))) as any} contentStyle={{ backgroundColor: 'white', border: '1px solid #e5e7eb', borderRadius: '8px', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)' }} />
                      <Legend formatter={(value) => <span style={{ color: THEME.textMain, fontSize: '12px' }}>{(value as string).split("/").pop() || value}</span>} />
                    </PieChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Model Usage Summary */}
          {metrics?.by_model && metrics.by_model.length > 0 && (
            <Card className="border-0 shadow-sm">
              <CardHeader>
                <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                  <Cpu className="h-5 w-5" style={{ color: THEME.chartColors[4] }} />
                  Model Usage Summary
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow className="border-gray-100">
                      <TableHead style={{ color: THEME.textSecondary }}>Model</TableHead>
                      <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Calls</TableHead>
                      <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Tokens</TableHead>
                      <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Cost</TableHead>
                      <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Share</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {metrics.by_model.slice(0, 5).map((model, idx) => {
                      const totalTokens = metrics.by_model.reduce((sum, m) => sum + m.total_tokens, 0);
                      const share = totalTokens > 0 ? (model.total_tokens / totalTokens) * 100 : 0;
                      return (
                        <TableRow key={model.model} className="border-gray-100 hover:bg-gray-50">
                          <TableCell className="font-medium" style={{ color: THEME.textMain }}>
                            <div className="flex items-center gap-2">
                              <div className="w-3 h-3 rounded-full" style={{ backgroundColor: THEME.chartColors[idx % THEME.chartColors.length] }} />
                              {model.model.split("/").pop() || model.model}
                            </div>
                          </TableCell>
                          <TableCell className="text-right" style={{ color: THEME.textMain }}>{model.call_count}</TableCell>
                          <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(model.total_tokens)}</TableCell>
                          <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatCost(model.total_cost)}</TableCell>
                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-2">
                              <ProgressBar value={share} max={100} color={THEME.chartColors[idx % THEME.chartColors.length]} showLabel={false} />
                              <span className="text-xs font-medium min-w-[40px]" style={{ color: THEME.textSecondary }}>{share.toFixed(1)}%</span>
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {/* Recent Sessions */}
          {sessionsData?.sessions && sessionsData.sessions.length > 0 && (
            <Card className="border-0 shadow-sm">
              <CardHeader>
                <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                  <Clock className="h-5 w-5" style={{ color: THEME.chartColors[3] }} />
                  Recent Sessions
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {sessionsData.sessions.slice(0, 5).map((session) => (
                    <div
                      key={session.session_id}
                      className={`flex items-center justify-between p-4 rounded-lg cursor-pointer transition-all hover:shadow-md ${session.has_errors ? 'bg-red-50 border border-red-100' : 'bg-gray-50 hover:bg-gray-100'}`}
                      onClick={() => onSelectSession(session.session_id)}
                    >
                      <div className="flex items-center gap-4">
                        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${session.has_errors ? 'bg-red-100' : 'bg-white'}`}>
                          {session.has_errors ? <XCircle className="h-5 w-5 text-red-500" /> : <Clock className="h-5 w-5" style={{ color: THEME.textSecondary }} />}
                        </div>
                        <div>
                          <p className="font-medium truncate max-w-[300px]" style={{ color: THEME.textMain }}>{session.session_id}</p>
                          <p className="text-sm" style={{ color: THEME.textSecondary }}>{session.trace_count} traces | {formatTokens(session.total_tokens)} tokens</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-4">
                        <span className="text-sm font-medium" style={{ color: THEME.primary }}>{formatCost(session.total_cost)}</span>
                        <ChevronRight className="h-5 w-5" style={{ color: THEME.textSecondary }} />
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
