import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { FolderOpen, Search, ChevronRight } from "lucide-react";
import { THEME } from "../theme";
import { formatCost, formatTokens } from "../utils";
import type { ProjectsResponse } from "../types";
import { TruncationBanner } from "./StatCard";

interface ProjectsTabProps {
  projectsData: ProjectsResponse | undefined;
  projectsLoading: boolean;
  projectsFetching: boolean;
  fetchAllMode: boolean;
  onLoadAll: () => void;
  onSelectProject: (id: string) => void;
}

export function ProjectsTab({ projectsData, projectsLoading, projectsFetching, fetchAllMode, onLoadAll, onSelectProject }: ProjectsTabProps) {
  const [search, setSearch] = useState("");
  const filtered = useMemo(() => {
    if (!projectsData?.projects) return [];
    if (!search.trim()) return projectsData.projects;
    const s = search.toLowerCase();
    return projectsData.projects.filter(p => p.project_name?.toLowerCase().includes(s));
  }, [projectsData?.projects, search]);

  const tabLoading = projectsLoading && !projectsData;

  return (
    <div className="space-y-4">
      {projectsData?.truncated && !fetchAllMode && (
        <TruncationBanner fetchedCount={projectsData.fetched_trace_count ?? 0} onLoadAll={onLoadAll} isLoading={projectsLoading || projectsFetching} />
      )}
      {tabLoading ? (
        <Skeleton className="h-64" />
      ) : (
        <Card className="border-0 shadow-sm">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                  <FolderOpen className="h-5 w-5" style={{ color: THEME.chartColors[3] }} />
                  Projects
                </CardTitle>
                <CardDescription style={{ color: THEME.textSecondary }}>Your projects with aggregated metrics</CardDescription>
              </div>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4" style={{ color: THEME.textSecondary }} />
                <Input placeholder="Search projects..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9 h-9 w-64 bg-gray-50 border-gray-200" />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {filtered.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow className="border-gray-100">
                    <TableHead style={{ color: THEME.textSecondary }}>Project</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Agents</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Traces</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Sessions</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Tokens</TableHead>
                    <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Cost</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((project) => (
                    <TableRow key={project.project_id} className="cursor-pointer border-gray-100 hover:bg-gray-50" onClick={() => onSelectProject(project.project_id)}>
                      <TableCell className="font-medium" style={{ color: THEME.textMain }}>
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${THEME.chartColors[3]}15` }}>
                            <FolderOpen className="h-4 w-4" style={{ color: THEME.chartColors[3] }} />
                          </div>
                          {project.project_name}
                        </div>
                      </TableCell>
                      <TableCell className="text-right" style={{ color: THEME.textMain }}>{project.agent_count ?? 0}</TableCell>
                      <TableCell className="text-right" style={{ color: THEME.textMain }}>{project.trace_count ?? 0}</TableCell>
                      <TableCell className="text-right" style={{ color: THEME.textMain }}>{project.session_count ?? 0}</TableCell>
                      <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(project.total_tokens ?? 0)}</TableCell>
                      <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatCost(project.total_cost ?? 0)}</TableCell>
                      <TableCell><ChevronRight className="h-4 w-4" style={{ color: THEME.textSecondary }} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="text-center py-12">
                <FolderOpen className="h-12 w-12 mx-auto mb-4" style={{ color: THEME.textSecondary }} />
                <p style={{ color: THEME.textSecondary }}>{search ? `No projects found matching "${search}"` : "No projects found. Organize your agents into folders to see project metrics."}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
