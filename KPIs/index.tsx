import {
  Activity,
  BarChart3,
  LineChart,
  ChevronDown,
  ChevronUp,
  Server,
  ShieldCheck,
  GitBranch,
  Users,
  ClipboardCheck,
  UserCog,
  Database,
  Microscope,
  Zap,
  Code2,
  TrendingUp,
  Star,
  DollarSign,
  BarChart2,
  AlertTriangle,
} from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  LineChart as ReLineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  BarChart as ReBarChart,
  Bar,
  PieChart as RePieChart,
  Pie,
  Cell,
  Area,
  AreaChart,
} from "recharts";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Globe } from "lucide-react";
import { useTranslation } from "react-i18next";
import { AuthContext } from "@/contexts/authContext";
import { api } from "@/controllers/API/api";
import useRegionStore from "@/stores/regionStore";

type SectionId =
  | "platform"
  | "governance"
  | "cost"
  | "lifecycle"
  | "usage"
  | "approval"
  | "hitl"
  | "rag"
  | "quality"
  | "performance"
  | "code"
  | "productivity"
  | "experience"
  | "roi"
  | "maturity"
  | "risk";

type SectionKpi = {
  name: string;
  value: string;
  scope?: "global" | "local";
};

type ChartType = "line" | "bar" | "donut" | "area";

type LineConfig = {
  key: string;
  color: string;
};

type SectionChart = {
  title: string;
  subtitle: string;
  type: ChartType;
  data: { label: string; value?: number; [key: string]: number | string | undefined }[];
  lines?: LineConfig[];
  xKey?: string;
  xType?: "number" | "category";
  xTickFormatter?: (value: number) => string;
  placeholder?: boolean;
  scope?: "global" | "local";
};

type SectionConfig = {
  id: SectionId;
  label: string;
  headline: string;
  description: string;
  kpis: SectionKpi[];
  charts: SectionChart[];
};

type DashboardKpiApi = {
  id: string;
  label: string;
  value: number;
  unit?: string | null;
};

type DashboardSectionApiResponse = {
  section: string;
  kpis: DashboardKpiApi[];
};

type PendingSeriesPoint = {
  date: string;
  value: number;
};

type PendingSeriesResponse = {
  range: string;
  series: PendingSeriesPoint[];
};

type HitlSeriesResponse = {
  range: string;
  series: PendingSeriesPoint[];
};

const formatPercentMetric = (value: number | null | undefined): string => {
  if (value == null || !Number.isFinite(value)) return "0%";
  return `${value.toFixed(2)}%`;
};

// --- Section Definitions (data unchanged from original) -------------------

const sections: SectionConfig[] = [
  {
    id: "platform",
    label: "Platform Health & Reliability",
    headline: "Platform Health & Reliability KPIs",
    description: "Infrastructure uptime, API latency percentiles, error rates, and AKS cluster resource saturation.",
    kpis: [
      { name: "Platform Uptime %", value: "0%", scope: "global" },
      { name: "API Latency P95", value: "0ms", scope: "global" },
      { name: "API Latency P99", value: "0ms", scope: "global" },
      { name: "Error Rate %", value: "0%", scope: "global" },
      { name: "Running Pods", value: "0" },
      { name: "AKS Pod Scaling Events", value: "0" },
      { name: "CPU/Memory Saturation %", value: "0%", scope: "global" },
      { name: "Total Runs", value: "0" },
      { name: "Total Failed Runs", value: "0" },
      { name: "Execution Failure Rate", value: "0%" },
    ],
    charts: [
      {
        title: "API Latency P95 vs P99",
        subtitle: "Latency comparison (24h)",
        type: "line",
        data: [],
        scope: "global",
        lines: [{ key: "p95", color: "#2563eb" }, { key: "p99", color: "#f97316" }],
        xKey: "ts",
        xType: "number",
        xTickFormatter: (v) => new Date(v * 1000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      },
      {
        title: "Error Rate Trend",
        subtitle: "Error rate over time (24h)",
        type: "area",
        data: [],
        scope: "global",
        xKey: "ts",
        xType: "number",
        xTickFormatter: (v) => new Date(v * 1000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      },
      {
        title: "CPU & Memory Saturation",
        subtitle: "Cluster utilization (24h)",
        type: "line",
        data: [],
        scope: "global",
        lines: [{ key: "cpu", color: "#0ea5e9" }, { key: "memory", color: "#14b8a6" }],
        xKey: "ts",
        xType: "number",
        xTickFormatter: (v) => new Date(v * 1000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      },
    ],
  },
  {
    id: "governance",
    label: "Governance & Guardrail",
    headline: "Governance & Guardrail KPIs",
    description: "Policy enforcement and agents operating without guardrails.",
    kpis: [
      { name: "Guardrail Violation Rate", value: "0%" },
      { name: "Escalation to Human Review", value: "0" },
      { name: "% Agents Without Guardrails", value: "0%" },
      { name: "Policy Breach Attempts", value: "0" },
    ],
    charts: [],
  },
  {
    id: "cost",
    label: "Cost & Financial",
    headline: "Cost & Financial KPIs",
    description: "Agent execution costs, average cost per run, and monthly cost trends.",
    kpis: [
      { name: "Total Cost", value: "$0" },
      { name: "Avg Cost Per Run", value: "$0" },
    ],
    charts: [
      {
        title: "Monthly Cost Trend",
        subtitle: "Daily cost over time",
        type: "area",
        data: [],
      },
    ],
  },
  {
    id: "lifecycle",
    label: "Environment & Lifecycle",
    headline: "Environment & Lifecycle Governance",
    description: "Agent promotion across UAT and production, conversion rates, and deprecated agent tracking.",
    kpis: [],
    charts: [],
  },
];

const departmentSections: SectionConfig[] = [
  {
    id: "usage",
    label: "Department Usage",
    headline: "Department Usage KPIs",
    description: "Active agents and response performance across your department.",
    kpis: [
      { name: "Active Agents in Dept (UAT)", value: "0" },
      { name: "Active Agents in Dept (PROD)", value: "0" },
      { name: "Avg Response Time", value: "0ms", scope: "global" },
    ],
    charts: [
      { title: "Response Time Trend", subtitle: "Avg response time over time", type: "area", data: [], scope: "global" },
    ],
  },
  {
    id: "approval",
    label: "Approval & Governance",
    headline: "Approval & Governance KPIs",
    description: "Pending approval queue depth, rejection rates, and average approval time.",
    kpis: [
      { name: "Pending Approvals", value: "0" },
      { name: "Rejection Rate", value: "0%" },
      { name: "Avg Approval Time", value: "0min" },
    ],
    charts: [
      {
        title: "Pending Approvals",
        subtitle: "Queue trend",
        type: "area",
        data: [],
      },
    ],
  },
  {
    id: "hitl",
    label: "HITL Governance",
    headline: "HITL Governance KPIs",
    description: "Human-in-the-loop invocation frequency, response time benchmarks, and escalation patterns.",
    kpis: [
      { name: "Agents with HITL", value: "0" },
      { name: "HITL Invocation Rate", value: "0%" },
      { name: "Avg HITL Response Time", value: "0min" },
    ],
    charts: [
      {
        title: "Invocation Rate",
        subtitle: "Daily trend",
        type: "area",
        data: [],
      },
      {
        title: "Response Time",
        subtitle: "Minutes by day",
        type: "bar",
        data: [],
      },
    ],
  },
  
];

const developerSections: SectionConfig[] = [
  
  {
    id: "performance",
    label: "Performance",
    headline: "Performance KPIs",
    description: "Agent response latency profiles - P95, and P99 percentiles to surface tail latency regressions.",
    kpis: [
      { name: "Avg Agent Latency", value: "0ms", scope: "global" },
      { name: "Latency P95", value: "0ms", scope: "global" },
      { name: "Latency P99", value: "0ms", scope: "global" },
    ],
    charts: [
      {
        title: "API Latency P95 vs P99",
        subtitle: "Latency comparison",
        type: "line",
        data: [],
        scope: "global",
        lines: [{ key: "p95", color: "#2563eb" }, { key: "p99", color: "#f97316" }],
        xKey: "ts",
        xType: "number",
        xTickFormatter: (v) => new Date(v * 1000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      },
    ],
  },
  
];

const businessSections: SectionConfig[] = [
  
  {
    id: "experience",
    label: "Experience",
    headline: "Experience KPIs",
    description: "End-user experience signals - response speed, satisfaction scores, and escalation frequency to human agents.",
    kpis: [
      { name: "Avg Response Time", value: "0ms", scope: "global" },
      { name: "Avg Session Duration", value: "0ms" },
      { name: "User Satisfaction Score", value: "0" },
      { name: "Escalation to Human", value: "0" },
    ],
    charts: [
      { title: "Response Time", subtitle: "Daily trend", type: "area", data: [], scope: "global" },
    ],
  },
];

const rootSections: SectionConfig[] = [

  {
    id: "maturity",
    label: "AI Maturity Indicators",
    headline: "AI Maturity Indicators",
    description: "Governance capability - adoption guardrails, RAG, and HITL coverage as signals of AI maturity.",
    kpis: [
      { name: "% Agents with Guardrails", value: "0%" },
      { name: "% Agents with RAG", value: "0%" },
      { name: "% Agents with HITL", value: "0%" },
    ],
    charts: [],
  },
  {
    id: "cost",
    label: "ROI & Financial Health",
    headline: "ROI & Financial Health",
    description: "95th percentile cost per agent run over time — highlights expensive outlier runs.",
    kpis: [],
    charts: [
      {
        title: "Cost P95 Trend",
        subtitle: "Daily P95 cost per run",
        type: "area",
        data: [],
      },
    ],
  },

];

// --- Style constants -------------------------------------------------------

const chartColors = ["#2563eb", "#14b8a6", "#f97316", "#a855f7"];

const sectionThemes: Record<SectionId, { badge: string; accent: string; border: string; headerBg: string; iconBg: string; icon: React.ReactNode }> = {
  platform:    { badge: "bg-sky-100 text-sky-700",         accent: "#0ea5e9", border: "border-l-sky-500",     headerBg: "bg-sky-50/60 dark:bg-sky-950/20",     iconBg: "bg-sky-100 dark:bg-sky-900/30",     icon: <Server className="h-4 w-4 text-sky-600 dark:text-sky-400" /> },
  governance:  { badge: "bg-emerald-100 text-emerald-700", accent: "#10b981", border: "border-l-emerald-500", headerBg: "bg-emerald-50/60 dark:bg-emerald-950/20", iconBg: "bg-emerald-100 dark:bg-emerald-900/30", icon: <ShieldCheck className="h-4 w-4 text-emerald-600 dark:text-emerald-400" /> },
  cost:        { badge: "bg-amber-100 text-amber-700",     accent: "#f59e0b", border: "border-l-amber-500",   headerBg: "bg-amber-50/60 dark:bg-amber-950/20",   iconBg: "bg-amber-100 dark:bg-amber-900/30",   icon: <DollarSign className="h-4 w-4 text-amber-600 dark:text-amber-400" /> },
  lifecycle:   { badge: "bg-violet-100 text-violet-700",   accent: "#8b5cf6", border: "border-l-violet-500",  headerBg: "bg-violet-50/60 dark:bg-violet-950/20", iconBg: "bg-violet-100 dark:bg-violet-900/30", icon: <GitBranch className="h-4 w-4 text-violet-600 dark:text-violet-400" /> },
  usage:       { badge: "bg-sky-100 text-sky-700",         accent: "#0ea5e9", border: "border-l-sky-500",     headerBg: "bg-sky-50/60 dark:bg-sky-950/20",     iconBg: "bg-sky-100 dark:bg-sky-900/30",     icon: <Users className="h-4 w-4 text-sky-600 dark:text-sky-400" /> },
  approval:    { badge: "bg-amber-100 text-amber-700",     accent: "#f59e0b", border: "border-l-amber-500",   headerBg: "bg-amber-50/60 dark:bg-amber-950/20",   iconBg: "bg-amber-100 dark:bg-amber-900/30",   icon: <ClipboardCheck className="h-4 w-4 text-amber-600 dark:text-amber-400" /> },
  hitl:        { badge: "bg-emerald-100 text-emerald-700", accent: "#10b981", border: "border-l-emerald-500", headerBg: "bg-emerald-50/60 dark:bg-emerald-950/20", iconBg: "bg-emerald-100 dark:bg-emerald-900/30", icon: <UserCog className="h-4 w-4 text-emerald-600 dark:text-emerald-400" /> },
  rag:         { badge: "bg-violet-100 text-violet-700",   accent: "#8b5cf6", border: "border-l-violet-500",  headerBg: "bg-violet-50/60 dark:bg-violet-950/20", iconBg: "bg-violet-100 dark:bg-violet-900/30", icon: <Database className="h-4 w-4 text-violet-600 dark:text-violet-400" /> },
  quality:     { badge: "bg-sky-100 text-sky-700",         accent: "#0ea5e9", border: "border-l-sky-500",     headerBg: "bg-sky-50/60 dark:bg-sky-950/20",     iconBg: "bg-sky-100 dark:bg-sky-900/30",     icon: <Microscope className="h-4 w-4 text-sky-600 dark:text-sky-400" /> },
  performance: { badge: "bg-emerald-100 text-emerald-700", accent: "#10b981", border: "border-l-emerald-500", headerBg: "bg-emerald-50/60 dark:bg-emerald-950/20", iconBg: "bg-emerald-100 dark:bg-emerald-900/30", icon: <Zap className="h-4 w-4 text-emerald-600 dark:text-emerald-400" /> },
  code:        { badge: "bg-amber-100 text-amber-700",     accent: "#f59e0b", border: "border-l-amber-500",   headerBg: "bg-amber-50/60 dark:bg-amber-950/20",   iconBg: "bg-amber-100 dark:bg-amber-900/30",   icon: <Code2 className="h-4 w-4 text-amber-600 dark:text-amber-400" /> },
  productivity:{ badge: "bg-sky-100 text-sky-700",         accent: "#0ea5e9", border: "border-l-sky-500",     headerBg: "bg-sky-50/60 dark:bg-sky-950/20",     iconBg: "bg-sky-100 dark:bg-sky-900/30",     icon: <TrendingUp className="h-4 w-4 text-sky-600 dark:text-sky-400" /> },
  experience:  { badge: "bg-emerald-100 text-emerald-700", accent: "#10b981", border: "border-l-emerald-500", headerBg: "bg-emerald-50/60 dark:bg-emerald-950/20", iconBg: "bg-emerald-100 dark:bg-emerald-900/30", icon: <Star className="h-4 w-4 text-emerald-600 dark:text-emerald-400" /> },
  roi:         { badge: "bg-sky-100 text-sky-700",         accent: "#0ea5e9", border: "border-l-sky-500",     headerBg: "bg-sky-50/60 dark:bg-sky-950/20",     iconBg: "bg-sky-100 dark:bg-sky-900/30",     icon: <DollarSign className="h-4 w-4 text-sky-600 dark:text-sky-400" /> },
  maturity:    { badge: "bg-emerald-100 text-emerald-700", accent: "#10b981", border: "border-l-emerald-500", headerBg: "bg-emerald-50/60 dark:bg-emerald-950/20", iconBg: "bg-emerald-100 dark:bg-emerald-900/30", icon: <BarChart2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" /> },
  risk:        { badge: "bg-rose-100 text-rose-700",       accent: "#f43f5e", border: "border-l-rose-500",    headerBg: "bg-rose-50/60 dark:bg-rose-950/20",     iconBg: "bg-rose-100 dark:bg-rose-900/30",     icon: <AlertTriangle className="h-4 w-4 text-rose-600 dark:text-rose-400" /> },
};

// --- Tooltips -------------------------------------------------------------

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { value: number; name?: string; dataKey?: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow">
      <p className="font-semibold text-foreground">{label}</p>
      {payload.map((e) => (
        <p key={e.dataKey ?? e.name ?? e.value} className="text-muted-foreground">
          {(e.name ?? e.dataKey ?? "value")}: {e.value}
        </p>
      ))}
    </div>
  );
}

function DonutTooltip({ active, payload }: { active?: boolean; payload?: { name: string; value: number }[] }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow">
      <p className="font-semibold text-foreground">{payload[0].name}</p>
      <p className="text-muted-foreground">{payload[0].value}</p>
    </div>
  );
}

// --- Chart Size Helper ------------------------------------------------------

function ChartSize({
  className,
  children,
}: {
  className?: string;
  children: (size: { width: number; height: number }) => React.ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const update = () => {
      const rect = el.getBoundingClientRect();
      const next = {
        width: Math.floor(rect.width),
        height: Math.floor(rect.height),
      };
      setSize((prev) =>
        prev.width === next.width && prev.height === next.height ? prev : next,
      );
    };

    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={containerRef} className={className}>
      {size.width > 0 && size.height > 0 ? children(size) : null}
    </div>
  );
}
// --- Chart Block -----------------------------------------------------------

function ChartBlock({ chart, accentColor }: { chart: SectionChart; accentColor: string }) {
  if (chart.type === "area") {
    const xKey = chart.xKey ?? "label";
    const xType = chart.xType ?? "category";
    const gradId = `grad-${chart.title.replace(/\W/g, "")}`;
    return (
      <div className="h-44">
        <ChartSize className="h-full w-full">{({ width, height }) => (
          <AreaChart width={width} height={height} data={chart.data} margin={{ top: 8, right: 12, left: -10, bottom: 0 }}>
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={accentColor} stopOpacity={0.15} />
                <stop offset="95%" stopColor={accentColor} stopOpacity={0.01} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey={xKey} type={xType} domain={xType === "number" ? ["dataMin", "dataMax"] : undefined} tickFormatter={xType === "number" ? chart.xTickFormatter : undefined} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
            <Tooltip content={<ChartTooltip />} labelFormatter={xType === "number" && chart.xTickFormatter ? chart.xTickFormatter : undefined} />
            <Area type="monotone" dataKey="value" stroke={accentColor} strokeWidth={2} fill={`url(#${gradId})`} dot={false} connectNulls />
          </AreaChart>
        )}</ChartSize>
      </div>
    );
  }

  if (chart.type === "line") {
    const xKey = chart.xKey ?? "label";
    const xType = chart.xType ?? "category";
    return (
      <div className="h-44">
        <ChartSize className="h-full w-full">{({ width, height }) => (
          <ReLineChart width={width} height={height} data={chart.data} margin={{ top: 8, right: 12, left: -10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey={xKey} type={xType} domain={xType === "number" ? ["dataMin", "dataMax"] : undefined} tickFormatter={xType === "number" ? chart.xTickFormatter : undefined} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
            <Tooltip content={<ChartTooltip />} labelFormatter={xType === "number" && chart.xTickFormatter ? chart.xTickFormatter : undefined} />
            {chart.lines?.length
              ? chart.lines.map((l) => <Line key={l.key} type="monotone" dataKey={l.key} stroke={l.color} strokeWidth={2} dot={false} connectNulls />)
              : <Line type="monotone" dataKey="value" stroke={accentColor} strokeWidth={2} dot={false} connectNulls />}
          </ReLineChart>
        )}</ChartSize>
      </div>
    );
  }

  if (chart.type === "bar") {
    return (
      <div className="h-44">
        <ChartSize className="h-full w-full">{({ width, height }) => (
          <ReBarChart width={width} height={height} data={chart.data} margin={{ top: 8, right: 12, left: -10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
            <Tooltip content={<ChartTooltip />} />
            <Bar dataKey="value" radius={[5, 5, 0, 0]}>
              {chart.data.map((e, i) => <Cell key={String(e.label)} fill={chartColors[i % chartColors.length]} />)}
            </Bar>
          </ReBarChart>
        )}</ChartSize>
      </div>
    );
  }

  return (
    <div className="flex h-44 items-center gap-4">
      <ChartSize className="h-full w-1/2">{({ width, height }) => (
        <RePieChart width={width} height={height}>
          <Pie data={chart.data} dataKey="value" nameKey="label" innerRadius={38} outerRadius={62} paddingAngle={2}>
            {chart.data.map((e, i) => <Cell key={String(e.label)} fill={chartColors[i % chartColors.length]} />)}
          </Pie>
          <Tooltip content={<DonutTooltip />} />
        </RePieChart>
      )}</ChartSize>
      <div className="space-y-2">
        {chart.data.map((slice, i) => (
          <div key={String(slice.label)} className="flex items-center gap-2 text-xs">
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: chartColors[i % chartColors.length] }} />
            <span className="text-muted-foreground">{slice.label}</span>
            <span className="font-semibold text-foreground">{slice.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}



// --- Section Card ----------------------------------------------------------

function SectionCard({
  section,
  displayKpis,
  charts,
  approvalRangeSelector,
  hitlRangeSelector,
  costRangeSelector,
  costP95RangeSelector,
  defaultExpanded,
}: {
  section: SectionConfig;
  displayKpis: SectionKpi[];
  charts: SectionChart[];
  approvalRangeSelector?: React.ReactNode;
  hitlRangeSelector?: React.ReactNode;
  costRangeSelector?: React.ReactNode;
  costP95RangeSelector?: React.ReactNode;
  defaultExpanded: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const { t } = useTranslation();
  const theme = sectionThemes[section.id];
  const isEmpty = displayKpis.length === 0 && charts.length === 0;
  const isMaturity = section.id === "maturity";

  return (
    <div
      className={`overflow-hidden rounded-2xl border border-border border-l-4 ${theme.border} bg-card shadow-sm transition-shadow duration-200 ${expanded ? "shadow-md" : "hover:shadow-md"}`}
    >
      {/* -- Clickable Header -- */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={`flex w-full items-center justify-between px-5 py-5 text-left transition-colors ${theme.headerBg} hover:brightness-95`}
      >
        {/* Left: icon + label + description */}
        <div className="flex items-center gap-3 min-w-0">
          {/* Icon badge */}
          <div className={`shrink-0 flex h-8 w-8 items-center justify-center rounded-lg ${theme.iconBg}`}>
            {theme.icon}
          </div>

          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-foreground leading-tight">
                {t(section.label)}
              </span>
              {isEmpty && (
                <span className="text-xxs text-muted-foreground rounded-full border border-border bg-background px-2 py-0.5 leading-none">
                  No data configured
                </span>
              )}
            </div>
            <p className="mt-0.5 text-xxs text-muted-foreground truncate max-w-xl hidden sm:block">
              {section.description}
            </p>
          </div>
        </div>

        {/* Right: meta + chevron */}
        <div className="flex shrink-0 items-center gap-3 ml-4">
          {!isEmpty && (
            <div className="hidden sm:flex items-center gap-1.5">
              {displayKpis.length > 0 && (
                <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xxs font-medium ${theme.badge}`}>
                  {displayKpis.length} KPI{displayKpis.length !== 1 ? "s" : ""}
                </span>
              )}
              {charts.length > 0 && (
                <span className="inline-flex items-center rounded-full border border-border bg-background px-2 py-0.5 text-xxs font-medium text-muted-foreground">
                  {charts.length} chart{charts.length !== 1 ? "s" : ""}
                </span>
              )}
            </div>
          )}
          <div className={`rounded-full p-1 transition-colors ${expanded ? theme.iconBg : "bg-transparent"}`}>
            {expanded
              ? <ChevronUp className="h-4 w-4 text-muted-foreground" />
              : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
          </div>
        </div>
      </button>

      {/* -- Collapsed Preview - KPI chips visible when closed -- */}
      {!expanded && !isEmpty && displayKpis.length > 0 && (
        <div
          className="border-t border-border px-5 py-3 flex flex-wrap gap-2"
          style={{ backgroundColor: theme.accent + "06" }}
        >
          {displayKpis.map((kpi) => (
            <div
              key={kpi.name}
              className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 shadow-sm"
            >
              <span className="h-1.5 w-1.5 rounded-full shrink-0" style={{ backgroundColor: theme.accent }} />
              <span className="text-xxs text-muted-foreground">{t(kpi.name)}</span>
              {kpi.scope === "global" && (
                <span className="rounded-full border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-xxs font-bold uppercase tracking-wide text-sky-700">
                  Global
                </span>
              )}
              <span className="text-xxs font-bold text-foreground">{kpi.value}</span>
            </div>
          ))}
        </div>
      )}

      {/* -- Expanded Body -- */}
      {expanded && !isEmpty && (
        <div className="border-t border-border bg-card px-6 pb-6">

          {/* KPI grid - uses section accent color consistently */}
          {displayKpis.length > 0 && (
            <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
              {displayKpis.map((kpi, i) => (
                <div
                  key={kpi.name}
                  className="group relative overflow-hidden rounded-xl border border-border bg-card p-4 shadow-sm transition-all duration-150 hover:-translate-y-0.5 hover:shadow-md"
                >
                  {/* Left accent stripe */}
                  <div
                    className="absolute left-0 top-0 bottom-0 w-0.5 rounded-l-xl"
                    style={{ backgroundColor: theme.accent }}
                  />
                  {/* Index dot */}
                  <div
                    className="mb-3 flex h-6 w-6 items-center justify-center rounded-full text-xxs font-bold text-white"
                    style={{ backgroundColor: theme.accent + "cc" }}
                  >
                    {i + 1}
                  </div>
                  <div className="flex items-center gap-2">
                    <p className="text-xxs uppercase tracking-widest text-muted-foreground leading-snug font-medium">
                      {t(kpi.name)}
                    </p>
                    {kpi.scope === "global" && (
                      <span className="rounded-full border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-xxs font-bold uppercase tracking-wide text-sky-700">
                        Global
                      </span>
                    )}
                  </div>
                  <p className="mt-2 text-2xl font-bold text-foreground leading-none tracking-tight">
                    {kpi.value}
                  </p>
                  {/* subtle bg glow */}
                  <div
                    className="pointer-events-none absolute -right-4 -bottom-4 h-16 w-16 rounded-full opacity-[0.05] group-hover:opacity-[0.10] transition-opacity"
                    style={{ backgroundColor: theme.accent }}
                  />
                </div>
              ))}
            </div>
          )}

          

          {/* Charts */}
          {charts.length > 0 && (
            <>
              {/* Divider with label */}
              <div className="mt-6 mb-4 flex items-center gap-3">
                <div className="h-px flex-1 bg-border" />
                <span className="text-xxs font-semibold uppercase tracking-widest text-muted-foreground">
                  Charts
                </span>
                <div className="h-px flex-1 bg-border" />
              </div>

              <div className={`grid grid-cols-1 gap-4 ${charts.length === 1 ? "lg:grid-cols-2" : "lg:grid-cols-2 xl:grid-cols-3"}`}>
                {charts.map((chart) => {
                  const isApprovalChart = section.id === "approval" && chart.title === "Pending Approvals";
                  const isHitlChart = section.id === "hitl" && (chart.title === "Invocation Rate" || chart.title === "Response Time");
                  const isCostChart = section.id === "cost" && chart.title === "Monthly Cost Trend";
                  const isCostP95Chart = section.id === "cost" && chart.title === "Cost P95 Trend";
                  return (
                    <div
                      key={chart.title}
                      className="overflow-hidden rounded-xl border border-border bg-background shadow-sm"
                    >
                      {/* Chart header strip */}
                      <div
                        className="flex items-center justify-between px-4 py-3 border-b border-border"
                        style={{ backgroundColor: theme.accent + "0d" }}
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-semibold text-foreground leading-tight truncate">
                              {t(chart.title)}
                            </p>
                            {chart.scope === "global" && (
                              <span className="rounded-full border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-xxs font-bold uppercase tracking-wide text-sky-700">
                                Global
                              </span>
                            )}
                          </div>
                          <p className="text-xxs text-muted-foreground mt-0.5">{t(chart.subtitle)}</p>
                        </div>
                        <div className="shrink-0 ml-3">
                          {isApprovalChart && approvalRangeSelector}
                          {isHitlChart && hitlRangeSelector}
                          {isCostChart && costRangeSelector}
                          {isCostP95Chart && costP95RangeSelector}
                          {!isApprovalChart && !isHitlChart && !isCostChart && !isCostP95Chart && (
                            <div
                              className="rounded-lg p-1.5"
                              style={{ backgroundColor: theme.accent + "1a" }}
                            >
                              {chart.type === "line" || chart.type === "area"
                                ? <LineChart className="h-3.5 w-3.5" style={{ color: theme.accent }} />
                                : chart.type === "bar"
                                  ? <BarChart3 className="h-3.5 w-3.5" style={{ color: theme.accent }} />
                                  : <Activity className="h-3.5 w-3.5" style={{ color: theme.accent }} />}
                            </div>
                          )}
                        </div>
                      </div>
                      {/* Chart body */}
                      <div className="p-4">
                        <ChartBlock chart={chart} accentColor={theme.accent} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// --- Main Component --------------------------------------------------------

export default function DashboardAdmin(): JSX.Element {
  const { t } = useTranslation();
  const { role, userData } = useContext(AuthContext);
  const normalizedRole = (role ?? "").toLowerCase().trim().replace(/\s+/g, "_");
  const isDepartmentAdmin = normalizedRole === "department_admin";
  const isDeveloper       = normalizedRole === "developer";
  const isBusinessUser    = normalizedRole === "business_user";
  const isRootAdmin       = normalizedRole === "root";
  const isSuperAdmin      = normalizedRole === "super_admin";
  const isLeaderExecutive = normalizedRole === "leader_executive";

  // ── Region selector (root admin only) ──────────────────────────────────
  const regions = useRegionStore((s) => s.regions);
  const selectedRegionCode = useRegionStore((s) => s.selectedRegionCode);
  const setSelectedRegion = useRegionStore((s) => s.setSelectedRegion);
  const fetchRegions = useRegionStore((s) => s.fetchRegions);

  useEffect(() => {
    if (isRootAdmin) {
      fetchRegions();
    }
  }, [isRootAdmin]);

  // Helper: build axios config with region header
  const regionHeaders = useMemo(() => {
    if (!isRootAdmin || !selectedRegionCode) return {};
    return { "X-Region-Code": selectedRegionCode };
  }, [isRootAdmin, selectedRegionCode]);

  const regionConfig = useMemo(() => {
    if (!isRootAdmin || !selectedRegionCode) return undefined;
    return { headers: regionHeaders };
  }, [isRootAdmin, selectedRegionCode, regionHeaders]);

  const isRemoteRegion = useMemo(() => {
    if (!selectedRegionCode || !regions.length) return false;
    const hub = regions.find((r) => r.is_hub);
    return hub ? hub.code !== selectedRegionCode : false;
  }, [selectedRegionCode, regions]);

  const [lifecycleKpis, setLifecycleKpis]         = useState<SectionKpi[] | null>(null);
  const [governanceKpis, setGovernanceKpis]         = useState<SectionKpi[] | null>(null);
  const [deptUsageKpis, setDeptUsageKpis]           = useState<SectionKpi[] | null>(null);
  const [deptApprovalKpis, setDeptApprovalKpis]     = useState<SectionKpi[] | null>(null);
  const [deptResponseTimeSeries, setDeptResponseTimeSeries] = useState<PendingSeriesPoint[] | null>(null);
  const [approvalRange, setApprovalRange]           = useState<"7d" | "30d" | "12w">("7d");
  const [approvalPendingSeries, setApprovalPendingSeries] = useState<PendingSeriesPoint[] | null>(null);
  const [refreshTick, setRefreshTick]               = useState(0);
  const [deptHitlKpis, setDeptHitlKpis]             = useState<SectionKpi[] | null>(null);
  const [hitlRange, setHitlRange]                   = useState<"7d" | "30d" | "12w">("7d");
  const [hitlInvocationSeries, setHitlInvocationSeries] = useState<PendingSeriesPoint[] | null>(null);
  const [hitlResponseSeries, setHitlResponseSeries] = useState<PendingSeriesPoint[] | null>(null);
  const tzOffsetMinutes = useMemo(() => -new Date().getTimezoneOffset(), []);
  const [devCodeKpis, setDevCodeKpis]               = useState<SectionKpi[] | null>(null);
  const [businessMaturityKpis, setBusinessMaturityKpis] = useState<SectionKpi[] | null>(null);
  const [rootMaturityKpis, setRootMaturityKpis]     = useState<SectionKpi[] | null>(null);
  const [platformKpis, setPlatformKpis]             = useState<SectionKpi[] | null>(null);
  const [platformLatencySeries, setPlatformLatencySeries] = useState<Array<{ label: string; ts: number; p95?: number; p99?: number }> | null>(null);
  const [platformErrorSeries, setPlatformErrorSeries]     = useState<Array<{ label: string; ts: number; value?: number }> | null>(null);
  const [platformCpuMemSeries, setPlatformCpuMemSeries]   = useState<Array<{ label: string; ts: number; cpu?: number; memory?: number }> | null>(null);
  const [devPerformanceKpis, setDevPerformanceKpis] = useState<SectionKpi[] | null>(null);
  const [devLatencySeries, setDevLatencySeries]     = useState<Array<{ label: string; p95?: number; p99?: number }> | null>(null);
  const [businessExperienceKpis, setBusinessExperienceKpis] = useState<SectionKpi[] | null>(null);
  const [businessResponseTimeSeries, setBusinessResponseTimeSeries] = useState<PendingSeriesPoint[] | null>(null);
  const [costKpis, setCostKpis]                           = useState<SectionKpi[] | null>(null);
  const [costRange, setCostRange]                         = useState<"30d" | "90d">("30d");
  const [costTrendSeries, setCostTrendSeries]             = useState<PendingSeriesPoint[] | null>(null);
  const [costP95Range, setCostP95Range]                   = useState<"30d" | "90d">("30d");
  const [costP95TrendSeries, setCostP95TrendSeries]       = useState<PendingSeriesPoint[] | null>(null);

  // Fallbacks
  const lifecycleKpiFallback:   SectionKpi[] = [{ name: "Agents in UAT", value: "0" }, { name: "UAT to PROD Conversion Rate", value: "0%" }, { name: "Deprecated Agent Count", value: "0" }];
  const governanceKpiFallback:  SectionKpi[] = [{ name: "Guardrail Violation Rate", value: "0%" }, { name: "Escalation to Human Review", value: "0" }, { name: "% Agents Without Guardrails", value: "0%" }, { name: "Policy Breach Attempts", value: "0" }];
  const deptUsageKpiFallback:   SectionKpi[] = [{ name: "Active Agents in Dept (UAT)", value: "0" }, { name: "Active Agents in Dept (PROD)", value: "0" }, { name: "Avg Response Time", value: "0ms" }];
  const deptApprovalKpiFallback:SectionKpi[] = [{ name: "Pending Approvals", value: "0" }, { name: "Rejection Rate", value: "0%" }, { name: "Avg Approval Time", value: "0min" }];
  const deptHitlKpiFallback:    SectionKpi[] = [{ name: "Agents with HITL", value: "0" }, { name: "HITL Invocation Rate", value: "0%" }, { name: "Avg HITL Response Time", value: "0min" }];
  const devCodeKpiFallback:     SectionKpi[] = [{ name: "Avg. Version Count of Agents", value: "0" }];
  const businessMaturityFallback:SectionKpi[]= [{ name: "% Agents with Guardrails", value: "0%" }, { name: "% Agents with RAG", value: "0%" }, { name: "% Agents with HITL", value: "0%" }];
  const rootMaturityFallback:   SectionKpi[] = [{ name: "% Agents with Guardrails", value: "0%" }, { name: "% Agents with RAG", value: "0%" }, { name: "% Agents with HITL", value: "0%" }];
  const platformKpiFallback:    SectionKpi[] = [{ name: "Platform Uptime %", value: "0%" }, { name: "API Latency P95", value: "0ms" }, { name: "API Latency P99", value: "0ms" }, { name: "Error Rate %", value: "0%" }, { name: "Running Pods", value: "0" }, { name: "AKS Pod Scaling Events", value: "0" }, { name: "CPU/Memory Saturation %", value: "0%" }, { name: "Total Agent Runs", value: "0" }, { name: "Failed Agent Runs", value: "0" }, { name: "Execution Failure Rate", value: "0%" }];
  const costKpiFallback:        SectionKpi[] = [{ name: "Total Cost", value: "$0.00" }, { name: "Avg Cost Per Run", value: "$0.00" }];
  const devPerformanceFallback: SectionKpi[] = [{ name: "Avg Agent Latency", value: "0ms" }, { name: "Latency P95", value: "0ms" }, { name: "Latency P99", value: "0ms" }];
  const businessExperienceFallback:SectionKpi[]=[{ name: "Avg Response Time", value: "0ms" }, { name: "Avg Session Duration", value: "0ms" }, { name: "Escalation to Human", value: "0" }, { name: "User Satisfaction Score", value: "0" }];
  const approvalRangeOptions = [{ value: "7d", label: "Last 7 days" }, { value: "30d", label: "Last 30 days" }, { value: "12w", label: "Last 12 weeks" }];

  useEffect(() => { const id = setInterval(() => setRefreshTick((t) => t + 1), 15000); return () => clearInterval(id); }, []);

  // ── All API calls preserved exactly from original ──────────────────────
  useEffect(() => { if (!isSuperAdmin && !isRootAdmin) return; const orgId = userData?.organization_id || null; const p: any = { ...(regionConfig || {}), params: orgId ? { org_id: orgId } : undefined }; api.get<DashboardSectionApiResponse>("/api/dashboard/sections/environment-lifecycle", p).then((r) => setLifecycleKpis(r.data?.kpis?.map((k) => ({ name: k.label, value: k.unit ? `${k.value}${k.unit}` : `${k.value}` })) ?? lifecycleKpiFallback)).catch(() => setLifecycleKpis(lifecycleKpiFallback)); }, [isSuperAdmin, isRootAdmin, refreshTick, userData?.organization_id, selectedRegionCode]);
  useEffect(() => {
    if (!isSuperAdmin) return;
    const gv = (p: any) => { const r = p?.data?.result; const v = Array.isArray(r) && r.length > 0 ? r[0]?.value?.[1] : null; const n = v != null ? Number(v) : null; return Number.isFinite(n) ? n : null; };
    const gsv = (sp: any, label: string) => { const s = sp?.series ?? []; const e = s.find((x: any) => x?.label === label); return (e?.prometheus?.data?.result?.[0]?.values ?? []).map((v: any) => Number(v?.[1] ?? 0)).filter((v: any) => Number.isFinite(v)); };
    const latestSeriesValue = (sp: any, label: string) => { const vals = gsv(sp, label); return vals.length ? vals[vals.length - 1] : null; };
    const now = Math.floor(Date.now() / 1000); const start = now - 86400;
    Promise.all([api.get(`/api/metrics-dashboard/query-preset/platform_uptime`), api.get(`/api/metrics-dashboard/query-preset/api_latency_p95`), api.get(`/api/metrics-dashboard/query-preset/api_latency_p99`), api.get(`/api/metrics-dashboard/query-preset/error_rate`), api.get(`/api/metrics-dashboard/query-preset/cpu_saturation`), api.get(`/api/metrics-dashboard/query-preset/memory_saturation`), api.get(`/api/metrics-dashboard/query-preset-range/pod_scaling_activity`, { params: { start, end: now, step: "3600s" } }), api.get(`/api/metrics-dashboard/query-preset-range/cpu_memory_saturation`, { params: { start, end: now, step: "120s" } })])
      .then(([u, p95, p99, er, cpu, mem, sc, cm]) => {
        const uv = gv(u?.data?.prometheus), p95v = gv(p95?.data?.prometheus), p99v = gv(p99?.data?.prometheus), erv = gv(er?.data?.prometheus);
        const cpuv = gv(cpu?.data?.prometheus) ?? latestSeriesValue(cm?.data, "CPU %");
        const memv = gv(mem?.data?.prometheus) ?? latestSeriesValue(cm?.data, "Memory %");
        const dv = gsv(sc?.data, "Desired Replicas (HPA)"); let se = 0; for (let i = 1; i < dv.length; i++) if (dv[i] !== dv[i-1]) se++;
        const rv = gsv(sc?.data, "Running Pods"); const runningPods = rv.length > 0 ? Math.round(rv[rv.length - 1]) : null;
        const cpuMemValue = cpuv != null || memv != null ? `${cpuv != null ? formatPercentMetric(cpuv) : "--"} / ${memv != null ? formatPercentMetric(memv) : "--"}` : "0%";
        const promKpis = [{ name: "Platform Uptime %", value: uv != null ? `${uv.toFixed(2)}%` : "0%" }, { name: "API Latency P95", value: p95v != null ? `${Math.round(p95v)}ms` : "0ms" }, { name: "API Latency P99", value: p99v != null ? `${Math.round(p99v)}ms` : "0ms" }, { name: "Error Rate %", value: erv != null ? `${erv.toFixed(2)}%` : "0%" }, { name: "Running Pods", value: runningPods != null ? `${runningPods}` : "0" }, { name: "AKS Pod Scaling Events", value: `${se}` }, { name: "CPU/Memory Saturation %", value: cpuMemValue }];
        const promNames = new Set(promKpis.map((k) => k.name));
        setPlatformKpis((prev) => {
          const base = prev ?? platformKpiFallback;
          return [...base.filter((k) => !promNames.has(k.name)), ...promKpis];
        });
      }).catch(() => {});
  }, [isSuperAdmin, refreshTick]);
  useEffect(() => {
    if (!isSuperAdmin) return;
    const now = Math.floor(Date.now() / 1000); const start = now - 86400;
    const fmt = (ts: number) => new Date(ts * 1000).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    Promise.all([api.get(`/api/metrics-dashboard/query-preset-range/api_latency_comparison`, { params: { start, end: now, step: "60s" } }), api.get(`/api/metrics-dashboard/query-preset-range/error_rate_trend`, { params: { start, end: now, step: "120s" } }), api.get(`/api/metrics-dashboard/query-preset-range/cpu_memory_saturation`, { params: { start, end: now, step: "120s" } })])
      .then(([lat, er, cm]) => {
        const lm: Record<number, any> = {}; for (const s of lat?.data?.series ?? []) { const lk = s?.label === "P95" ? "p95" : s?.label === "P99" ? "p99" : null; if (!lk) continue; for (const v of s?.prometheus?.data?.result?.[0]?.values ?? []) { const ts = Number(v?.[0] ?? 0); if (!Number.isFinite(ts)) continue; if (!lm[ts]) lm[ts] = { label: fmt(ts), ts }; const val = Number(v?.[1] ?? 0); if (Number.isFinite(val)) lm[ts][lk] = val; } }
        setPlatformLatencySeries(Object.entries(lm).sort(([a], [b]) => +a - +b).map(([, p]) => p));
        const et = (er?.data?.series ?? []).find((s: any) => s?.label === "Error Rate") ?? er?.data?.series?.[0];
        setPlatformErrorSeries((et?.prometheus?.data?.result?.[0]?.values ?? []).map((v: any) => { const ts = Number(v?.[0] ?? 0); const val = Number(v?.[1] ?? 0); return Number.isFinite(ts) && Number.isFinite(val) ? { label: fmt(ts), ts, value: val } : null; }).filter(Boolean));
        const cmm: Record<number, any> = {}; for (const s of cm?.data?.series ?? []) { const lk = s?.label === "CPU %" ? "cpu" : s?.label === "Memory %" ? "memory" : null; if (!lk) continue; for (const v of s?.prometheus?.data?.result?.[0]?.values ?? []) { const ts = Number(v?.[0] ?? 0); if (!Number.isFinite(ts)) continue; if (!cmm[ts]) cmm[ts] = { label: fmt(ts), ts }; const val = Number(v?.[1] ?? 0); if (Number.isFinite(val)) cmm[ts][lk] = val; } }
        setPlatformCpuMemSeries(Object.entries(cmm).sort(([a], [b]) => +a - +b).map(([, p]) => p));
      }).catch(() => { setPlatformLatencySeries([]); setPlatformErrorSeries([]); setPlatformCpuMemSeries([]); });
  }, [isSuperAdmin, refreshTick]);
  useEffect(() => { if (!isDepartmentAdmin) return; api.get<DashboardSectionApiResponse>("/api/dashboard/sections/department-usage").then((r) => setDeptUsageKpis(r.data?.kpis?.map((k) => ({ name: k.label, value: k.unit ? `${k.value}${k.unit}` : `${k.value}` })) ?? deptUsageKpiFallback)).catch(() => setDeptUsageKpis(deptUsageKpiFallback)); }, [isDepartmentAdmin, refreshTick]);
  useEffect(() => { if (!isDepartmentAdmin) return; api.get(`/api/metrics-dashboard/query-preset/avg_response_time`).then((r) => { const res = r?.data?.prometheus?.data?.result; const v = Array.isArray(res) && res.length > 0 ? res[0]?.value?.[1] : null; const n = v != null ? Number(v) : null; if (Number.isFinite(n)) setDeptUsageKpis((prev) => { const next = prev ? [...prev] : [...deptUsageKpiFallback]; const idx = next.findIndex((k) => k.name === "Avg Response Time"); if (idx >= 0) next[idx] = { ...next[idx], value: `${Math.round(n!)}ms` }; else next.push({ name: "Avg Response Time", value: `${Math.round(n!)}ms` }); return next; }); }).catch(() => setDeptUsageKpis((p) => p ?? deptUsageKpiFallback)); }, [isDepartmentAdmin, refreshTick]);
  useEffect(() => { if (!isDepartmentAdmin) return; const now = Math.floor(Date.now() / 1000); api.get(`/api/metrics-dashboard/query-preset-range/response_time_trend`, { params: { start: now - 604800, end: now, step: "3600s" } }).then((r) => setDeptResponseTimeSeries((r?.data?.series?.[0]?.prometheus?.data?.result?.[0]?.values ?? []).map((v: any) => ({ date: new Date(Number(v?.[0] ?? 0) * 1000).toISOString().slice(0, 10), value: Number.isFinite(Number(v?.[1] ?? 0)) ? Number(v[1]) : 0 })))).catch(() => setDeptResponseTimeSeries([])); }, [isDepartmentAdmin, refreshTick]);
  useEffect(() => { if (!isDepartmentAdmin) return; api.get<DashboardSectionApiResponse>("/api/dashboard/sections/department-approval").then((r) => setDeptApprovalKpis(r.data?.kpis?.map((k) => ({ name: k.label, value: k.unit ? `${k.value}${k.unit}` : `${k.value}` })) ?? deptApprovalKpiFallback)).catch(() => setDeptApprovalKpis(deptApprovalKpiFallback)); }, [isDepartmentAdmin, refreshTick]);
  useEffect(() => { if (!isDepartmentAdmin) return; api.get<DashboardSectionApiResponse>("/api/dashboard/sections/department-hitl").then((r) => setDeptHitlKpis(r.data?.kpis?.map((k) => ({ name: k.label, value: k.unit ? `${k.value}${k.unit}` : `${k.value}` })) ?? deptHitlKpiFallback)).catch(() => setDeptHitlKpis(deptHitlKpiFallback)); }, [isDepartmentAdmin, refreshTick]);
  useEffect(() => { if (!isDeveloper) return; api.get<DashboardSectionApiResponse>("/api/dashboard/sections/developer-code").then((r) => setDevCodeKpis(r.data?.kpis?.map((k) => ({ name: k.label, value: k.unit ? `${k.value}${k.unit}` : `${k.value}` })) ?? devCodeKpiFallback)).catch(() => setDevCodeKpis(devCodeKpiFallback)); }, [isDeveloper, refreshTick]);
  useEffect(() => {
    if (!isDeveloper) return;
    Promise.all([api.get(`/api/metrics-dashboard/query-preset/avg_agent_latency`), api.get(`/api/metrics-dashboard/query-preset/api_latency_p95`), api.get(`/api/metrics-dashboard/query-preset/api_latency_p99`)]).then(([avg, p95, p99]) => {
      const gv = (p: any) => { const r = p?.data?.result; const v = Array.isArray(r) && r.length > 0 ? r[0]?.value?.[1] : null; const n = v != null ? Number(v) : null; return Number.isFinite(n) ? n : null; };
      setDevPerformanceKpis([{ name: "Avg Agent Latency", value: gv(avg?.data?.prometheus) != null ? `${Math.round(gv(avg?.data?.prometheus)!)}ms` : "0ms" }, { name: "Latency P95", value: gv(p95?.data?.prometheus) != null ? `${Math.round(gv(p95?.data?.prometheus)!)}ms` : "0ms" }, { name: "Latency P99", value: gv(p99?.data?.prometheus) != null ? `${Math.round(gv(p99?.data?.prometheus)!)}ms` : "0ms" }]);
    }).catch(() => setDevPerformanceKpis(devPerformanceFallback));
  }, [isDeveloper, refreshTick]);
  useEffect(() => {
    if (!isDeveloper) return;
    const now = Math.floor(Date.now() / 1000); const start = now - 86400;
    api.get(`/api/metrics-dashboard/query-preset-range/api_latency_comparison`, { params: { start, end: now, step: "60s" } }).then((r) => {
      const merged: Record<number, any> = {};
      for (const s of r?.data?.series ?? []) { const lk = s?.label === "P95" ? "p95" : s?.label === "P99" ? "p99" : null; if (!lk) continue; for (const v of s?.prometheus?.data?.result?.[0]?.values ?? []) { const ts = Number(v?.[0] ?? 0); if (!Number.isFinite(ts)) continue; if (!merged[ts]) merged[ts] = { label: new Date(ts * 1000).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }), ts }; const val = Number(v?.[1] ?? 0); if (Number.isFinite(val)) merged[ts][lk] = val; } }
      setDevLatencySeries(Object.entries(merged).sort(([a], [b]) => +a - +b).map(([, p]) => p));
    }).catch(() => setDevLatencySeries([]));
  }, [isDeveloper, refreshTick]);
  useEffect(() => { if (!isBusinessUser) return; api.get<DashboardSectionApiResponse>("/api/dashboard/sections/business-maturity").then((r) => setBusinessMaturityKpis(r.data?.kpis?.map((k) => ({ name: k.label, value: k.unit ? `${k.value}${k.unit}` : `${k.value}` })) ?? businessMaturityFallback)).catch(() => setBusinessMaturityKpis(businessMaturityFallback)); }, [isBusinessUser, refreshTick]);
  useEffect(() => { if (!isBusinessUser) return; api.get(`/api/metrics-dashboard/query-preset/avg_response_time`).then((r) => { const res = r?.data?.prometheus?.data?.result; const v = Array.isArray(res) && res.length > 0 ? res[0]?.value?.[1] : null; const n = v != null ? Number(v) : null; if (!Number.isFinite(n)) { setBusinessExperienceKpis((p) => p ?? businessExperienceFallback); return; } setBusinessExperienceKpis((prev) => { const next = prev ? [...prev] : [...businessExperienceFallback]; const idx = next.findIndex((k) => k.name === "Avg Response Time"); if (idx >= 0) next[idx] = { ...next[idx], value: `${Math.round(n!)}ms` }; else next.push({ name: "Avg Response Time", value: `${Math.round(n!)}ms` }); return next; }); }).catch(() => setBusinessExperienceKpis((p) => p ?? businessExperienceFallback)); }, [isBusinessUser, refreshTick]);
  useEffect(() => { if (!isBusinessUser) return; api.get(`/api/metrics-dashboard/query-preset/avg_session_duration`).then((r) => { const res = r?.data?.prometheus?.data?.result; const v = Array.isArray(res) && res.length > 0 ? res[0]?.value?.[1] : null; const n = v != null ? Number(v) : null; if (!Number.isFinite(n)) { setBusinessExperienceKpis((p) => p ?? businessExperienceFallback); return; } setBusinessExperienceKpis((prev) => { const next = prev ? [...prev] : [...businessExperienceFallback]; const idx = next.findIndex((k) => k.name === "Avg Session Duration"); if (idx >= 0) next[idx] = { ...next[idx], value: `${Math.round(n!)}ms` }; else next.push({ name: "Avg Session Duration", value: `${Math.round(n!)}ms` }); return next; }); }).catch(() => setBusinessExperienceKpis((p) => p ?? businessExperienceFallback)); }, [isBusinessUser, refreshTick]);
  useEffect(() => { if (!isBusinessUser) return; const now = Math.floor(Date.now() / 1000); api.get(`/api/metrics-dashboard/query-preset-range/response_time_trend`, { params: { start: now - 604800, end: now, step: "3600s" } }).then((r) => setBusinessResponseTimeSeries((r?.data?.series?.[0]?.prometheus?.data?.result?.[0]?.values ?? []).map((v: any) => ({ date: new Date(Number(v?.[0] ?? 0) * 1000).toISOString().slice(0, 10), value: Number.isFinite(Number(v?.[1] ?? 0)) ? Number(v[1]) : 0 })))).catch(() => setBusinessResponseTimeSeries([])); }, [isBusinessUser, refreshTick]);
  useEffect(() => { if (!isBusinessUser) return; api.get<DashboardSectionApiResponse>("/api/dashboard/sections/business-experience").then((r) => { const next = r.data?.kpis?.map((k) => ({ name: k.label, value: k.unit ? `${k.value}${k.unit}` : `${k.value}` })) ?? []; setBusinessExperienceKpis((prev) => { const m = new Map((prev ?? businessExperienceFallback).map((k) => [k.name, k.value])); for (const k of next) m.set(k.name, k.value); return Array.from(m.entries()).map(([name, value]) => ({ name, value })); }); }).catch(() => setBusinessExperienceKpis((p) => p ?? businessExperienceFallback)); }, [isBusinessUser, refreshTick]);
  useEffect(() => { if (!isRootAdmin && !isLeaderExecutive) return; api.get<DashboardSectionApiResponse>("/api/dashboard/sections/root-maturity", regionConfig).then((r) => setRootMaturityKpis(r.data?.kpis?.map((k) => ({ name: k.label, value: k.unit ? `${k.value}${k.unit}` : `${k.value}` })) ?? rootMaturityFallback)).catch(() => setRootMaturityKpis(rootMaturityFallback)); }, [isRootAdmin, isLeaderExecutive, refreshTick, selectedRegionCode]);
  useEffect(() => {
    if (!isLeaderExecutive) return;
    api.get<PendingSeriesResponse>("/api/dashboard/sections/cost-p95-trend", {
      ...(regionConfig || {}),
      params: { range: costP95Range, tz_offset_minutes: tzOffsetMinutes },
    })
      .then((r) => setCostP95TrendSeries(r.data?.series ?? []))
      .catch(() => setCostP95TrendSeries([]));
  }, [costP95Range, isLeaderExecutive, refreshTick, selectedRegionCode, tzOffsetMinutes]);
  useEffect(() => {
    if (!isDepartmentAdmin) return;
    api
      .get<PendingSeriesResponse>("/api/dashboard/sections/department-approval/pending-series", {
        params: { range: approvalRange, tz_offset_minutes: tzOffsetMinutes },
      })
      .then((r) => {
        setApprovalPendingSeries(r.data?.series ?? []);
      })
      .catch((err) => {
        console.log("[dashboard] approval pending-series error", err);
        setApprovalPendingSeries([]);
      });
  }, [approvalRange, isDepartmentAdmin, refreshTick, tzOffsetMinutes]);
  useEffect(() => {
    if (!isDepartmentAdmin) return;
    api
      .get<HitlSeriesResponse>("/api/dashboard/sections/department-hitl/invocation-series", {
        params: { range: hitlRange, tz_offset_minutes: tzOffsetMinutes },
      })
      .then((r) => {
        setHitlInvocationSeries(r.data?.series ?? []);
      })
      .catch(() => setHitlInvocationSeries([]));
  }, [hitlRange, isDepartmentAdmin, refreshTick, tzOffsetMinutes]);
  useEffect(() => {
    if (!isDepartmentAdmin) return;
    api
      .get<HitlSeriesResponse>("/api/dashboard/sections/department-hitl/response-time-series", {
        params: { range: hitlRange, tz_offset_minutes: tzOffsetMinutes },
      })
      .then((r) => {
        setHitlResponseSeries(r.data?.series ?? []);
      })
      .catch(() => setHitlResponseSeries([]));
  }, [hitlRange, isDepartmentAdmin, refreshTick, tzOffsetMinutes]);
  useEffect(() => { if (!isSuperAdmin && !isRootAdmin) return; const orgId = userData?.organization_id || null; const p: any = { ...(regionConfig || {}), params: orgId ? { org_id: orgId } : undefined }; api.get<DashboardSectionApiResponse>("/api/dashboard/sections/governance-guardrail", p).then((r) => setGovernanceKpis(r.data?.kpis?.map((k) => ({ name: k.label, value: k.unit ? `${k.value}${k.unit}` : `${k.value}` })) ?? governanceKpiFallback)).catch(() => setGovernanceKpis(governanceKpiFallback)); }, [isSuperAdmin, isRootAdmin, refreshTick, userData?.organization_id, selectedRegionCode]);
  useEffect(() => {
    if (!isSuperAdmin && !isRootAdmin) return;
    const orgId = userData?.organization_id || null;
    const p: any = { ...(regionConfig || {}), params: orgId ? { org_id: orgId } : undefined };
    api.get<DashboardSectionApiResponse>("/api/dashboard/sections/observability-health", p)
      .then((r) => {
        const mapped = r.data?.kpis?.map((k) => ({ name: k.label, value: k.unit ? `${k.value}${k.unit}` : `${k.value}` })) ?? [];
        setPlatformKpis((prev) => {
          const base = prev ?? platformKpiFallback;
          const obsNames = new Set(mapped.map((k) => k.name));
          return [...base.filter((k) => !obsNames.has(k.name)), ...mapped];
        });
      })
      .catch(() => {});
  }, [isSuperAdmin, isRootAdmin, refreshTick, userData?.organization_id, selectedRegionCode]);
  useEffect(() => {
    if (!isSuperAdmin && !isRootAdmin) return;
    const orgId = userData?.organization_id || null;
    const p: any = { ...(regionConfig || {}), params: orgId ? { org_id: orgId } : undefined };
    api.get<DashboardSectionApiResponse>("/api/dashboard/sections/cost-financial", p)
      .then((r) => setCostKpis(r.data?.kpis?.map((k) => ({ name: k.label, value: k.unit === "$" ? `$${k.value}` : k.unit ? `${k.value}${k.unit}` : `${k.value}` })) ?? costKpiFallback))
      .catch(() => setCostKpis(costKpiFallback));
  }, [isSuperAdmin, isRootAdmin, refreshTick, userData?.organization_id, selectedRegionCode]);
  useEffect(() => {
    if (!isSuperAdmin && !isRootAdmin) return;
    const orgId = userData?.organization_id || null;
    api.get<PendingSeriesResponse>("/api/dashboard/sections/cost-financial/monthly-trend", {
      ...(regionConfig || {}),
      params: { range: costRange, tz_offset_minutes: tzOffsetMinutes, ...(orgId ? { org_id: orgId } : {}) },
    })
      .then((r) => setCostTrendSeries(r.data?.series ?? []))
      .catch(() => setCostTrendSeries([]));
  }, [costRange, isSuperAdmin, isRootAdmin, refreshTick, userData?.organization_id, selectedRegionCode, tzOffsetMinutes]);

  // -- Chart data helpers ------------------------------------------------

  const mkDateSeries = (series: PendingSeriesPoint[] | null, days: number) => {
    const fb = Array.from({ length: days }, (_, i) => {
      const d = new Date();
      d.setDate(d.getDate() - (days - 1 - i));
      const localDate = new Date(d.getFullYear(), d.getMonth(), d.getDate());
      const dateStr = `${localDate.getFullYear()}-${String(localDate.getMonth() + 1).padStart(2, "0")}-${String(localDate.getDate()).padStart(2, "0")}`;
      return { date: dateStr, value: 0 };
    });
    return (series?.length ? series : fb).map((pt) => ({
      label: new Date(`${pt.date}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      value: pt.value,
    }));
  };
  const mkTsSeries = (n: number) => Array.from({ length: n }, (_, i) => { const ts = Math.floor(Date.now() / 1000) - (n - 1 - i) * 3600; return { label: new Date(ts * 1000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }), ts }; });

  const aDays = approvalRange === "7d" ? 7 : approvalRange === "30d" ? 30 : 84;
  const hDays = hitlRange === "7d" ? 7 : hitlRange === "30d" ? 30 : 84;

  const approvalChartData      = useMemo(() => mkDateSeries(approvalPendingSeries, aDays), [approvalPendingSeries, aDays]);
  const hitlInvocationChartData = useMemo(() => mkDateSeries(hitlInvocationSeries, hDays), [hitlInvocationSeries, hDays]);
  const hitlResponseChartData   = useMemo(() => mkDateSeries(hitlResponseSeries, hDays), [hitlResponseSeries, hDays]);
  const deptRtChartData         = useMemo(() => mkDateSeries(deptResponseTimeSeries, 7), [deptResponseTimeSeries]);
  const bizRtChartData          = useMemo(() => mkDateSeries(businessResponseTimeSeries, 7), [businessResponseTimeSeries]);
  const platLatencyData  = useMemo(() => platformLatencySeries?.length ? platformLatencySeries : mkTsSeries(8).map((p) => ({ ...p, p95: 0, p99: 0 })), [platformLatencySeries]);
  const platErrorData    = useMemo(() => platformErrorSeries?.length ? platformErrorSeries : mkTsSeries(8).map((p) => ({ ...p, value: 0 })), [platformErrorSeries]);
  const platCpuMemData   = useMemo(() => platformCpuMemSeries?.length ? platformCpuMemSeries : mkTsSeries(8).map((p) => ({ ...p, cpu: 0, memory: 0 })), [platformCpuMemSeries]);
  const cDays = costRange === "90d" ? 90 : 30;
  const costTrendChartData = useMemo(() => mkDateSeries(costTrendSeries, cDays), [costTrendSeries, cDays]);
  const cP95Days = costP95Range === "90d" ? 90 : 30;
  const costP95ChartData = useMemo(() => mkDateSeries(costP95TrendSeries, cP95Days), [costP95TrendSeries, cP95Days]);
  const devLatData       = useMemo(() => devLatencySeries ?? [], [devLatencySeries]);

  // -- Resolve KPIs + charts for each section ----------------------------

  const sectionsToRender = isDepartmentAdmin ? departmentSections : isDeveloper ? developerSections : isBusinessUser ? businessSections : isLeaderExecutive ? rootSections : isRootAdmin ? rootSections.filter((s) => s.id !== "cost") : sections;

  const resolveSection = (section: SectionConfig): { kpis: SectionKpi[]; charts: SectionChart[] } => {
    let kpis = [...section.kpis];

    const applyOverride = (overrides: SectionKpi[] | null) => {
      if (!overrides?.length) return;
      const map = new Map(overrides.map((k) => [k.name, k.value]));
      kpis = kpis.map((k) => ({ ...k, value: map.get(k.name) ?? k.value }));
    };

    if (isSuperAdmin && section.id === "lifecycle") kpis = lifecycleKpis ?? lifecycleKpiFallback;
    if (isSuperAdmin && section.id === "governance") applyOverride(governanceKpis);
    if (isSuperAdmin && section.id === "platform") applyOverride(platformKpis);
    if (isSuperAdmin && section.id === "cost") applyOverride(costKpis);
    if (isDepartmentAdmin && section.id === "usage") applyOverride(deptUsageKpis);
    if (isDepartmentAdmin && section.id === "approval") applyOverride(deptApprovalKpis);
    if (isDepartmentAdmin && section.id === "hitl") applyOverride(deptHitlKpis);
    if (isDeveloper && section.id === "code") applyOverride(devCodeKpis);
    if (isDeveloper && section.id === "performance") applyOverride(devPerformanceKpis);
    if ((isRootAdmin || isLeaderExecutive) && section.id === "maturity") applyOverride(rootMaturityKpis);
    if (isBusinessUser && section.id === "maturity") applyOverride(businessMaturityKpis);
    if (isBusinessUser && section.id === "experience") applyOverride(businessExperienceKpis);

    const charts = section.charts.map((chart) => {
      if (section.id === "platform") {
        if (chart.title === "API Latency P95 vs P99") return { ...chart, data: platLatencyData };
        if (chart.title === "Error Rate Trend")        return { ...chart, data: platErrorData };
        if (chart.title === "CPU & Memory Saturation") return { ...chart, data: platCpuMemData };
      }
      if (section.id === "cost" && chart.title === "Monthly Cost Trend") return { ...chart, data: costTrendChartData };
      if (section.id === "cost" && chart.title === "Cost P95 Trend") return { ...chart, data: costP95ChartData };
      if (section.id === "usage" && chart.title === "Response Time Trend") return { ...chart, data: deptRtChartData };
      if (section.id === "approval" && chart.title === "Pending Approvals") return { ...chart, data: approvalChartData };
      if (section.id === "hitl") {
        if (chart.title === "Invocation Rate") return { ...chart, data: hitlInvocationChartData };
        if (chart.title === "Response Time")   return { ...chart, data: hitlResponseChartData };
      }
      if (section.id === "performance" && chart.title === "API Latency P95 vs P99") return { ...chart, data: devLatData };
      if (section.id === "experience" && chart.title === "Response Time") return { ...chart, data: bizRtChartData };
      return chart;
    });

    return { kpis, charts };
  };

  const headerSubtitle = isDepartmentAdmin
    ? "Department Admin - Operational Governance"
    : isDeveloper
      ? "Developer - Build & Optimize"
      : isBusinessUser
        ? "Business User - Productivity & Experience"
        : isRootAdmin
          ? "Executive - Strategic Oversight"
          : "Super Admin - Full Organization View";

  const approvalRangeSelector = (
    <Select value={approvalRange} onValueChange={(v) => setApprovalRange(v as "7d" | "30d" | "12w")}>
      <SelectTrigger className="h-7 w-[130px] text-xs"><SelectValue /></SelectTrigger>
      <SelectContent>{approvalRangeOptions.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
    </Select>
  );
  const hitlRangeSelector = (
    <Select value={hitlRange} onValueChange={(v) => setHitlRange(v as "7d" | "30d" | "12w")}>
      <SelectTrigger className="h-7 w-[130px] text-xs"><SelectValue /></SelectTrigger>
      <SelectContent>{approvalRangeOptions.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
    </Select>
  );
  const costRangeOptions = [{ value: "30d", label: "Last 30 days" }, { value: "90d", label: "Last 90 days" }];
  const costRangeSelector = (
    <Select value={costRange} onValueChange={(v) => setCostRange(v as "30d" | "90d")}>
      <SelectTrigger className="h-7 w-[130px] text-xs"><SelectValue /></SelectTrigger>
      <SelectContent>{costRangeOptions.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
    </Select>
  );
  const costP95RangeSelector = (
    <Select value={costP95Range} onValueChange={(v) => setCostP95Range(v as "30d" | "90d")}>
      <SelectTrigger className="h-7 w-[130px] text-xs"><SelectValue /></SelectTrigger>
      <SelectContent>{costRangeOptions.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
    </Select>
  );

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* -- Page Header -- */}
      <div className="flex-shrink-0 border-b border-border bg-card">
        <div className="px-4 py-3 sm:px-6 md:px-8 md:py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-lg font-bold text-foreground md:text-xl">{t("Dashboard")}</h1>
              <div className="mt-1.5 flex items-center gap-2">
                <span className="inline-flex items-center rounded-full border border-border bg-background px-2.5 py-0.5 text-xxs font-medium text-muted-foreground">
                  {headerSubtitle}
                </span>
                <span className="text-muted-foreground text-xxs">-</span>
                <span className="text-xxs text-muted-foreground">
                  {sectionsToRender.length} section{sectionsToRender.length !== 1 ? "s" : ""}
                </span>
              </div>
            </div>

            {/* Region selector — root admin only */}
            {isRootAdmin && regions.length > 1 && (
              <div className="flex items-center gap-2">
                <Globe className="h-4 w-4 text-muted-foreground" />
                <Select value={selectedRegionCode ?? ""} onValueChange={setSelectedRegion}>
                  <SelectTrigger className="h-8 w-[160px] text-xs">
                    <SelectValue placeholder="Select Region" />
                  </SelectTrigger>
                  <SelectContent>
                    {regions.map((r) => (
                      <SelectItem key={r.code} value={r.code}>
                        {r.name}{r.is_hub ? " (Hub)" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Remote region banner ── */}
      {isRootAdmin && isRemoteRegion && selectedRegionCode && (
        <div className="flex-shrink-0 border-b border-amber-200 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-800 px-8 py-2.5">
          <div className="flex items-center justify-between">
            <p className="text-xs text-amber-800 dark:text-amber-200">
              Viewing dashboard data for <span className="font-semibold">{regions.find((r) => r.code === selectedRegionCode)?.name ?? selectedRegionCode}</span>. Data is read-only.
            </p>
            <button
              type="button"
              onClick={() => {
                const hub = regions.find((r) => r.is_hub);
                if (hub) setSelectedRegion(hub.code);
              }}
              className="text-xs font-medium text-amber-700 dark:text-amber-300 hover:underline"
            >
              Back to Home
            </button>
          </div>
        </div>
      )}

      {/* ── Section Stack ── */}
      <div className="flex-1 overflow-auto bg-background px-4 py-3 sm:px-6 md:px-8 md:py-4">
        <div className="space-y-4">
          {sectionsToRender.map((section, i) => {
            const { kpis, charts } = resolveSection(section);
            return (
              <SectionCard
                key={section.id}
                section={section}
                displayKpis={kpis}
                charts={charts}
                approvalRangeSelector={section.id === "approval" ? approvalRangeSelector : undefined}
                hitlRangeSelector={section.id === "hitl" ? hitlRangeSelector : undefined}
                costRangeSelector={section.id === "cost" ? costRangeSelector : undefined}
                costP95RangeSelector={section.id === "cost" ? costP95RangeSelector : undefined}
                defaultExpanded={i === 0}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
