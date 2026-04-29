import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Bot, ChevronRight } from "lucide-react";
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
                <CardTitle className="flex items-center gap-2 text-foreground">
                  <Bot className="h-5 w-5" style={{ color: THEME.primary }} />
                  Agents
                </CardTitle>
                <CardDescription className="text-muted-foreground">Your AI agents with usage metrics</CardDescription>
              </div>
              <div className="w-64">
                <Input icon="Search" placeholder="Search agents..." value={search} onChange={(e) => setSearch(e.target.value)} inputClassName="h-9 bg-muted/50 border-border" />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {filtered.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow className="border-border">
                    <TableHead className="text-muted-foreground">Agent</TableHead>
                    <TableHead className="text-muted-foreground">Project</TableHead>
                    <TableHead className="text-right text-muted-foreground">Traces</TableHead>
                    <TableHead className="text-right text-muted-foreground">Sessions</TableHead>
                    <TableHead className="text-right text-muted-foreground">Tokens</TableHead>
                    <TableHead className="text-right text-muted-foreground">Cost</TableHead>
                    <TableHead className="text-right text-muted-foreground">Status</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((agent) => (
                    <TableRow key={agent.agent_id} className="cursor-pointer border-border hover:bg-muted/50" onClick={() => onSelectAgent(agent.agent_id)}>
                      <TableCell className="font-medium text-foreground">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${THEME.primary}10` }}>
                            <Bot className="h-4 w-4" style={{ color: THEME.primary }} />
                          </div>
                          {agent.agent_name}
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{agent.project_name || "-"}</TableCell>
                      <TableCell className="text-right text-foreground">{agent.trace_count ?? 0}</TableCell>
                      <TableCell className="text-right text-foreground">{agent.session_count ?? 0}</TableCell>
                      <TableCell className="text-right text-foreground">{formatTokens(agent.total_tokens ?? 0)}</TableCell>
                      <TableCell className="text-right text-foreground">{formatCost(agent.total_cost ?? 0)}</TableCell>
                      <TableCell className="text-right">
                        {(agent.error_count ?? 0) > 0 ? (
                          <Badge style={{ backgroundColor: '#fee2e2', color: '#991b1b' }}>Error ({agent.error_count})</Badge>
                        ) : (
                          <Badge style={{ backgroundColor: '#dcfce7', color: '#166534' }}>OK</Badge>
                        )}
                      </TableCell>
                      <TableCell><ChevronRight className="h-4 w-4 text-muted-foreground" /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="text-center py-12">
                <Bot className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                <p className="text-muted-foreground">{search ? `No agents found matching "${search}"` : "No agents found. Run a agent to see agent metrics."}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
