import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from "recharts";
import { Cpu, Search, TrendingUp } from "lucide-react";
import { THEME } from "../theme";
import { formatCost, formatTokens, formatLatency } from "../utils";
import type { Metrics } from "../types";

interface ModelsTabProps {
  metrics: Metrics | undefined;
  metricsLoading: boolean;
}

export function ModelsTab({ metrics, metricsLoading }: ModelsTabProps) {
  const [search, setSearch] = useState("");
  const filteredModels = useMemo(() => {
    if (!metrics?.by_model) return [];
    if (!search.trim()) return metrics.by_model;
    const s = search.toLowerCase();
    return metrics.by_model.filter(m => m.model?.toLowerCase().includes(s));
  }, [metrics?.by_model, search]);

  if (metricsLoading) return <Skeleton className="h-64" />;

  return (
    <div className="space-y-4">
      <Card className="border-0 shadow-sm">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
              <Cpu className="h-5 w-5" style={{ color: THEME.chartColors[4] }} />
              Model Usage Breakdown
            </CardTitle>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4" style={{ color: THEME.textSecondary }} />
              <Input placeholder="Search models..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9 h-9 w-64 bg-gray-50 border-gray-200" />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {filteredModels.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow className="border-gray-100">
                  <TableHead style={{ color: THEME.textSecondary }}>Model</TableHead>
                  <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Calls</TableHead>
                  <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Input Tokens</TableHead>
                  <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Output Tokens</TableHead>
                  <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Total Tokens</TableHead>
                  <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Cost</TableHead>
                  <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Avg Latency</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredModels.map((model, idx) => (
                  <TableRow key={model.model} className="border-gray-100 hover:bg-gray-50">
                    <TableCell className="font-medium" style={{ color: THEME.textMain }}>
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded-full" style={{ backgroundColor: THEME.chartColors[idx % THEME.chartColors.length] }} />
                        {model.model}
                      </div>
                    </TableCell>
                    <TableCell className="text-right" style={{ color: THEME.textMain }}>{model.call_count}</TableCell>
                    <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(model.input_tokens)}</TableCell>
                    <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(model.output_tokens)}</TableCell>
                    <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(model.total_tokens)}</TableCell>
                    <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatCost(model.total_cost)}</TableCell>
                    <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatLatency(model.avg_latency_ms)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-center py-12">
              <Cpu className="h-12 w-12 mx-auto mb-4" style={{ color: THEME.textSecondary }} />
              <p style={{ color: THEME.textSecondary }}>{search ? `No models found matching "${search}"` : "No model usage data"}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {metrics?.top_agents && metrics.top_agents.length > 0 && (
        <Card className="border-0 shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
              <TrendingUp className="h-5 w-5" style={{ color: THEME.primary }} />
              Top Agents by Usage
            </CardTitle>
            <CardDescription style={{ color: THEME.textSecondary }}>agent execution count and token usage</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={Math.max(250, metrics.top_agents.length * 50)}>
              <BarChart
                data={metrics.top_agents.slice(0, 10).map(agent => ({ ...agent, shortName: agent.name.length > 25 ? agent.name.slice(0, 25) + '...' : agent.name }))}
                layout="vertical"
                margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" horizontal vertical={false} />
                <XAxis type="number" tick={{ fontSize: 12, fill: THEME.textSecondary }} axisLine={{ stroke: '#e5e7eb' }} />
                <YAxis type="category" dataKey="shortName" width={150} tick={{ fontSize: 11, fill: THEME.textMain }} axisLine={{ stroke: '#e5e7eb' }} />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload || !payload.length) return null;
                    const data = payload[0].payload;
                    return (
                      <div className="bg-white border shadow-lg rounded-lg p-3">
                        <p className="text-sm font-medium mb-2" style={{ color: THEME.textMain }}>{data.name}</p>
                        <div className="space-y-1 text-sm">
                          <div className="flex justify-between gap-4">
                            <span style={{ color: THEME.textSecondary }}>Count:</span>
                            <span className="font-medium" style={{ color: THEME.textMain }}>{data.count}</span>
                          </div>
                          <div className="flex justify-between gap-4">
                            <span style={{ color: THEME.textSecondary }}>Tokens:</span>
                            <span className="font-medium" style={{ color: THEME.textMain }}>{formatTokens(data.tokens)}</span>
                          </div>
                          <div className="flex justify-between gap-4">
                            <span style={{ color: THEME.textSecondary }}>Cost:</span>
                            <span className="font-medium" style={{ color: THEME.textMain }}>{formatCost(data.cost)}</span>
                          </div>
                        </div>
                      </div>
                    );
                  }}
                />
                <Legend />
                <Bar dataKey="count" fill={THEME.primary} name="Execution Count" radius={[0, 4, 4, 0]} />
                <Bar dataKey="tokens" fill={THEME.chartColors[1]} name="Tokens" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
