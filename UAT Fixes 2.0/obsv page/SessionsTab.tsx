import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Clock, ChevronRight, XCircle } from "lucide-react";
import { THEME } from "../theme";
import { formatCost, formatTokens, formatLatency } from "../utils";
import type { SessionsResponse } from "../types";
import { TruncationBanner } from "./StatCard";

interface SessionsTabProps {
  sessionsData: SessionsResponse | undefined;
  sessionsLoading: boolean;
  sessionsFetching: boolean;
  fetchAllMode: boolean;
  onLoadAll: () => void;
  onSelectSession: (id: string) => void;
}

export function SessionsTab({ sessionsData, sessionsLoading, sessionsFetching, fetchAllMode, onLoadAll, onSelectSession }: SessionsTabProps) {
  const [search, setSearch] = useState("");
  const filtered = useMemo(() => {
    if (!sessionsData?.sessions) return [];
    if (!search.trim()) return sessionsData.sessions;
    const s = search.toLowerCase();
    return sessionsData.sessions.filter(session =>
      session.session_id?.toLowerCase().includes(s) ||
      session.models_used?.some(model => model.toLowerCase().includes(s))
    );
  }, [sessionsData?.sessions, search]);

  const tabLoading = sessionsLoading && !sessionsData;

  return (
    <div className="space-y-4">
      {sessionsData?.truncated && !fetchAllMode && (
        <TruncationBanner fetchedCount={sessionsData.fetched_trace_count ?? 0} onLoadAll={onLoadAll} isLoading={sessionsLoading || sessionsFetching} />
      )}
      {tabLoading ? (
        <Skeleton className="h-64" />
      ) : (
        <Card className="border-0 shadow-sm">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2 text-foreground">
                  <Clock className="h-5 w-5" style={{ color: THEME.chartColors[1] }} />
                  Sessions
                </CardTitle>
                <CardDescription className="text-muted-foreground">Your chat sessions with metrics</CardDescription>
              </div>
              <div className="w-64">
                <Input icon="Search" placeholder="Search sessions..." value={search} onChange={(e) => setSearch(e.target.value)} inputClassName="h-9 bg-muted/50 border-border" />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {filtered.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow className="border-border">
                    <TableHead className="text-muted-foreground">Session ID</TableHead>
                    <TableHead className="text-right text-muted-foreground">Traces</TableHead>
                    <TableHead className="text-right text-muted-foreground">Tokens</TableHead>
                    <TableHead className="text-right text-muted-foreground">Cost</TableHead>
                    <TableHead className="text-right text-muted-foreground">Latency</TableHead>
                    <TableHead className="text-muted-foreground">Models</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((session) => (
                    <TableRow key={session.session_id} className={`cursor-pointer border-border hover:bg-muted/50 ${session.has_errors ? "bg-red-50/50" : ""}`} onClick={() => onSelectSession(session.session_id)}>
                      <TableCell className="font-medium max-w-[200px] truncate text-foreground">
                        <div className="flex items-center gap-2">
                          {session.has_errors && <XCircle className="h-4 w-4 text-red-500 flex-shrink-0" />}
                          {session.session_id}
                        </div>
                      </TableCell>
                      <TableCell className="text-right text-foreground">{session.trace_count}</TableCell>
                      <TableCell className="text-right text-foreground">{formatTokens(session.total_tokens)}</TableCell>
                      <TableCell className="text-right text-foreground">{formatCost(session.total_cost)}</TableCell>
                      <TableCell className="text-right text-foreground">{formatLatency(session.avg_latency_ms ?? null)}</TableCell>
                      <TableCell>
                        <div className="flex gap-1 flex-wrap">
                          {session.models_used.slice(0, 2).map((model) => (
                            <Badge key={model} variant="secondary" className="text-xs bg-muted text-foreground">{model.split("/").pop() || model}</Badge>
                          ))}
                          {session.models_used.length > 2 && (
                            <Badge variant="secondary" className="text-xs bg-muted text-muted-foreground">+{session.models_used.length - 2}</Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell><ChevronRight className="h-4 w-4 text-muted-foreground" /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="text-center py-12">
                <Clock className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                <p className="text-muted-foreground">{search ? `No sessions found matching "${search}"` : "No sessions found"}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
