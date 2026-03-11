import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Clock, Search, ChevronRight, XCircle } from "lucide-react";
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
                <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                  <Clock className="h-5 w-5" style={{ color: THEME.chartColors[1] }} />
                  Sessions
                </CardTitle>
                <CardDescription style={{ color: THEME.textSecondary }}>Your chat sessions with metrics</CardDescription>
              </div>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4" style={{ color: THEME.textSecondary }} />
                <Input placeholder="Search sessions..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9 h-9 w-64 bg-gray-50 border-gray-200" />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {filtered.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow className="border-gray-100">
                    <TableHead style={{ color: THEME.textSecondary }}>Session ID</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Traces</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Tokens</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Cost</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Latency</TableHead>
                    <TableHead style={{ color: THEME.textSecondary }}>Models</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((session) => (
                    <TableRow key={session.session_id} className={`cursor-pointer border-gray-100 hover:bg-gray-50 ${session.has_errors ? "bg-red-50/50" : ""}`} onClick={() => onSelectSession(session.session_id)}>
                      <TableCell className="font-medium max-w-[200px] truncate" style={{ color: THEME.textMain }}>
                        <div className="flex items-center gap-2">
                          {session.has_errors && <XCircle className="h-4 w-4 text-red-500 flex-shrink-0" />}
                          {session.session_id}
                        </div>
                      </TableCell>
                      <TableCell className="text-right" style={{ color: THEME.textMain }}>{session.trace_count}</TableCell>
                      <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(session.total_tokens)}</TableCell>
                      <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatCost(session.total_cost)}</TableCell>
                      <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatLatency(session.avg_latency_ms ?? null)}</TableCell>
                      <TableCell>
                        <div className="flex gap-1 flex-wrap">
                          {session.models_used.slice(0, 2).map((model) => (
                            <Badge key={model} variant="secondary" className="text-xs bg-gray-100" style={{ color: THEME.textMain }}>{model.split("/").pop() || model}</Badge>
                          ))}
                          {session.models_used.length > 2 && (
                            <Badge variant="secondary" className="text-xs bg-gray-100" style={{ color: THEME.textSecondary }}>+{session.models_used.length - 2}</Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell><ChevronRight className="h-4 w-4" style={{ color: THEME.textSecondary }} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="text-center py-12">
                <Clock className="h-12 w-12 mx-auto mb-4" style={{ color: THEME.textSecondary }} />
                <p style={{ color: THEME.textSecondary }}>{search ? `No sessions found matching "${search}"` : "No sessions found"}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
