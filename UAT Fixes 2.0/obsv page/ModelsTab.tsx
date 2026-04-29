import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from "recharts";
import { SafeResponsiveContainer } from "@/components/charts/SafeResponsiveContainer";
import { Cpu, TrendingUp } from "lucide-react";
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
            <CardTitle className="flex items-center gap-2 text-foreground">
              <Cpu className="h-5 w-5" style={{ color: THEME.chartColors[4] }} />
              Model Usage Breakdown
            </CardTitle>
            <div className="w-64">
              <Input icon="Search" placeholder="Search models..." value={search} onChange={(e) => setSearch(e.target.value)} inputClassName="h-9 bg-muted/50 border-border" />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {filteredModels.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow className="border-border">
                  <TableHead className="text-muted-foreground">Model</TableHead>
                  <TableHead className="text-right text-muted-foreground">Calls</TableHead>
                  <TableHead className="text-right text-muted-foreground">Input Tokens</TableHead>
                  <TableHead className="text-right text-muted-foreground">Output Tokens</TableHead>
                  <TableHead className="text-right text-muted-foreground">Total Tokens</TableHead>
                  <TableHead className="text-right text-muted-foreground">Cost</TableHead>
                  <TableHead className="text-right text-muted-foreground">Avg Latency</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredModels.map((model, idx) => (
                  <TableRow key={model.model} className="border-border hover:bg-muted/50">
                    <TableCell className="font-medium text-foreground">
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded-full" style={{ backgroundColor: THEME.chartColors[idx % THEME.chartColors.length] }} />
                        {model.model}
                      </div>
                    </TableCell>
                    <TableCell className="text-right text-foreground">{model.call_count}</TableCell>
                    <TableCell className="text-right text-foreground">{formatTokens(model.input_tokens)}</TableCell>
                    <TableCell className="text-right text-foreground">{formatTokens(model.output_tokens)}</TableCell>
                    <TableCell className="text-right text-foreground">{formatTokens(model.total_tokens)}</TableCell>
                    <TableCell className="text-right text-foreground">{formatCost(model.total_cost)}</TableCell>
                    <TableCell className="text-right text-foreground">{formatLatency(model.avg_latency_ms)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-center py-12">
              <Cpu className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
              <p className="text-muted-foreground">{search ? `No models found matching "${search}"` : "No model usage data"}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {metrics?.top_agents && metrics.top_agents.length > 0 && (
        <Card className="border-0 shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-foreground">
              <TrendingUp className="h-5 w-5" style={{ color: THEME.primary }} />
              Top Agents by Usage
            </CardTitle>
            <CardDescription className="text-muted-foreground">agent execution count and token usage</CardDescription>
          </CardHeader>
          <CardContent>
            <SafeResponsiveContainer width="100%" height={Math.max(250, metrics.top_agents.length * 50)}>
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
                      <div className="bg-card border shadow-lg rounded-lg p-3">
                        <p className="text-sm font-medium mb-2 text-foreground">{data.name}</p>
                        <div className="space-y-1 text-sm">
                          <div className="flex justify-between gap-4">
                            <span className="text-muted-foreground">Count:</span>
                            <span className="font-medium text-foreground">{data.count}</span>
                          </div>
                          <div className="flex justify-between gap-4">
                            <span className="text-muted-foreground">Tokens:</span>
                            <span className="font-medium text-foreground">{formatTokens(data.tokens)}</span>
                          </div>
                          <div className="flex justify-between gap-4">
                            <span className="text-muted-foreground">Cost:</span>
                            <span className="font-medium text-foreground">{formatCost(data.cost)}</span>
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
            </SafeResponsiveContainer>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
