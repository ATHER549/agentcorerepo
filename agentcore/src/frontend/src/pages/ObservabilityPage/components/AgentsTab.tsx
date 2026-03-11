import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Bot, Search, ChevronRight } from "lucide-react";
import { THEME } from "../theme";
import { formatCost, formatTokens } from "../utils";
import type { AgentsResponse } from "../types";
import { TruncationBanner } from "./StatCard";

interface AgentsTabProps {
  agentsData: AgentsResponse | undefined;
  agentsLoading: boolean;
  agentsFetching: boolean;
  fetchAllMode: boolean;
  onLoadAll: () => void;
  onSelectAgent: (id: string) => void;
}

export function AgentsTab({ agentsData, agentsLoading, agentsFetching, fetchAllMode, onLoadAll, onSelectAgent }: AgentsTabProps) {
  const [search, setSearch] = useState("");
  const filtered = useMemo(() => {
    if (!agentsData?.agents) return [];
    if (!search.trim()) return agentsData.agents;
    const s = search.toLowerCase();
    return agentsData.agents.filter(a => a.agent_name?.toLowerCase().includes(s));
  }, [agentsData?.agents, search]);

  const tabLoading = agentsLoading && !agentsData;

  return (
    <div className="space-y-4">
      {agentsData?.truncated && !fetchAllMode && (
        <TruncationBanner fetchedCount={agentsData.fetched_trace_count ?? 0} onLoadAll={onLoadAll} isLoading={agentsLoading || agentsFetching} />
      )}
      {tabLoading ? (
        <Skeleton className="h-64" />
      ) : (
        <Card className="border-0 shadow-sm">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                  <Bot className="h-5 w-5" style={{ color: THEME.primary }} />
                  Agents
                </CardTitle>
                <CardDescription style={{ color: THEME.textSecondary }}>Your AI agents with usage metrics</CardDescription>
              </div>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4" style={{ color: THEME.textSecondary }} />
                <Input placeholder="Search agents..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9 h-9 w-64 bg-gray-50 border-gray-200" />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {filtered.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow className="border-gray-100">
                    <TableHead style={{ color: THEME.textSecondary }}>Agent</TableHead>
                    <TableHead style={{ color: THEME.textSecondary }}>Project</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Traces</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Sessions</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Tokens</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Cost</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Status</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((agent) => (
                    <TableRow key={agent.agent_id} className="cursor-pointer border-gray-100 hover:bg-gray-50" onClick={() => onSelectAgent(agent.agent_id)}>
                      <TableCell className="font-medium" style={{ color: THEME.textMain }}>
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${THEME.primary}10` }}>
                            <Bot className="h-4 w-4" style={{ color: THEME.primary }} />
                          </div>
                          {agent.agent_name}
                        </div>
                      </TableCell>
                      <TableCell style={{ color: THEME.textSecondary }}>{agent.project_name || "-"}</TableCell>
                      <TableCell className="text-right" style={{ color: THEME.textMain }}>{agent.trace_count ?? 0}</TableCell>
                      <TableCell className="text-right" style={{ color: THEME.textMain }}>{agent.session_count ?? 0}</TableCell>
                      <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(agent.total_tokens ?? 0)}</TableCell>
                      <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatCost(agent.total_cost ?? 0)}</TableCell>
                      <TableCell className="text-right">
                        {(agent.error_count ?? 0) > 0 ? (
                          <Badge style={{ backgroundColor: '#fee2e2', color: '#991b1b' }}>Error ({agent.error_count})</Badge>
                        ) : (
                          <Badge style={{ backgroundColor: '#dcfce7', color: '#166534' }}>OK</Badge>
                        )}
                      </TableCell>
                      <TableCell><ChevronRight className="h-4 w-4" style={{ color: THEME.textSecondary }} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="text-center py-12">
                <Bot className="h-12 w-12 mx-auto mb-4" style={{ color: THEME.textSecondary }} />
                <p style={{ color: THEME.textSecondary }}>{search ? `No agents found matching "${search}"` : "No agents found. Run a agent to see agent metrics."}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
