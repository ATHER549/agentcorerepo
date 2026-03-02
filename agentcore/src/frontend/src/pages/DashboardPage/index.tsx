import {
  Plus,
  TrendingUp,
  Clock,
  DollarSign,
  Activity,
  Box,
  ArrowUpRight,
} from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useTranslation } from "react-i18next";

interface DashboardProps {
  onNewAgent?: () => void;
}

export default function DashboardAdmin(): JSX.Element {
  const { t } = useTranslation();
  const [timeFilter, setTimeFilter] = useState<"day" | "week" | "month" | "year">("day");

  /* ---------------------------------- Stats Data ---------------------------------- */

  const stats = [
    {
      icon: Box,
      label: "Total Projects",
      value: "28",
      change: "+5 this week",
      changePositive: true,
      color: "text-purple-500",
      bgColor: "bg-purple-500/10",
    },
    {
      icon: Activity,
      label: "Active Agents",
      value: "47",
      change: "+12 this month",
      changePositive: true,
      color: "text-blue-500",
      bgColor: "bg-blue-500/10",
    },
    {
      icon: Clock,
      label: "Avg Latency",
      value: "48ms",
      change: "-8ms improvement",
      changePositive: true,
      color: "text-green-500",
      bgColor: "bg-green-500/10",
    },
    {
      icon: TrendingUp,
      label: "Total Executions",
      value: "74K",
      change: "+18% this month",
      changePositive: true,
      color: "text-orange-500",
      bgColor: "bg-orange-500/10",
    },
  ];

  /* ---------------------------------- Recent Projects ---------------------------------- */

  const recentProjects = [
    {
      id: "1",
      name: "Customer Support Agent",
      type: "Conversational AI",
      
      color: "bg-pink-500",
      executions: "2.4K",
      lastEdited: "2 hours ago",
      status: "Active",
    },
    {
      id: "2",
      name: "Vector Store RAG",
      type: "Document Analysis",
      
      color: "bg-blue-500",
      executions: "1.8K",
      lastEdited: "5 hours ago",
      status: "Active",
    },
    {
      id: "3",
      name: "Data Extraction Pipeline",
      type: "ETL Process",
      
      color: "bg-green-500",
      executions: "3.2K",
      lastEdited: "1 day ago",
      status: "Active",
    },
    {
      id: "4",
      name: "Sentiment Analysis",
      type: "NLP Model",
      
      color: "bg-orange-500",
      executions: "856",
      lastEdited: "2 days ago",
      status: "Paused",
    },
  ];

  /* ---------------------------------- Project Status ---------------------------------- */

  const projectStatusByPeriod = {
    day: [
      { label: "Active", value: 12, color: "bg-purple-500" },
      { label: "Running", value: 8, color: "bg-blue-500" },
      { label: "Queued", value: 3, color: "bg-orange-500" },
      { label: "Completed", value: 5, color: "bg-green-500" },
    ],
    week: [
      { label: "Active", value: 12, color: "bg-purple-500" },
      { label: "In Development", value: 8, color: "bg-blue-500" },
      { label: "Paused", value: 3, color: "bg-orange-500" },
      { label: "Completed", value: 5, color: "bg-green-500" },
    ],
    month: [
      { label: "Active", value: 45, color: "bg-purple-500" },
      { label: "In Development", value: 28, color: "bg-blue-500" },
      { label: "Paused", value: 12, color: "bg-orange-500" },
      { label: "Completed", value: 38, color: "bg-green-500" },
    ],
    year: [
      { label: "Active", value: 156, color: "bg-purple-500" },
      { label: "In Development", value: 98, color: "bg-blue-500" },
      { label: "Paused", value: 45, color: "bg-orange-500" },
      { label: "Completed", value: 187, color: "bg-green-500" },
    ],
  };

  const projectStatus = projectStatusByPeriod[timeFilter];
  const total = projectStatus.reduce((sum, item) => sum + item.value, 0);

  /* ---------------------------------- Chart Data ---------------------------------- */

  const chartDataByPeriod = {
    day: [
      { label: "12 AM", requests: 320, executions: 145 },
      { label: "3 AM", requests: 280, executions: 120 },
      { label: "6 AM", requests: 450, executions: 210 },
      { label: "9 AM", requests: 820, executions: 380 },
      { label: "12 PM", requests: 950, executions: 450 },
      { label: "3 PM", requests: 880, executions: 420 },
      { label: "6 PM", requests: 720, executions: 340 },
      { label: "9 PM", requests: 540, executions: 250 },
    ],
    week: [
      { label: "Mon", requests: 4200, executions: 1850 },
      { label: "Tue", requests: 4800, executions: 2100 },
      { label: "Wed", requests: 4500, executions: 1950 },
      { label: "Thu", requests: 5200, executions: 2300 },
      { label: "Fri", requests: 5600, executions: 2500 },
      { label: "Sat", requests: 3800, executions: 1600 },
      { label: "Sun", requests: 3500, executions: 1500 },
    ],
    month: [
      { label: "Week 1", requests: 28000, executions: 12500 },
      { label: "Week 2", requests: 32000, executions: 14200 },
      { label: "Week 3", requests: 30500, executions: 13800 },
      { label: "Week 4", requests: 35000, executions: 15600 },
    ],
    year: [
      { label: "Jan", requests: 115000, executions: 52000 },
      { label: "Feb", requests: 125000, executions: 56000 },
      { label: "Mar", requests: 135000, executions: 61000 },
      { label: "Apr", requests: 142000, executions: 64000 },
      { label: "May", requests: 138000, executions: 62000 },
      { label: "Jun", requests: 145000, executions: 65500 },
      { label: "Jul", requests: 152000, executions: 68000 },
      { label: "Aug", requests: 148000, executions: 66500 },
      { label: "Sep", requests: 155000, executions: 69500 },
      { label: "Oct", requests: 162000, executions: 72500 },
      { label: "Nov", requests: 158000, executions: 71000 },
      { label: "Dec", requests: 165000, executions: 74000 },
    ],
  };

  const performanceData = chartDataByPeriod[timeFilter];

  /* ---------------------------------- JSX ---------------------------------- */

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 border-b bg-card">
        <div className="px-8 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold mb-2">
                {t("Dashboard")}
              </h1>
            
            </div>
           
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-8">
        {/* Time Filter Buttons */}
        <div className="flex gap-2 mb-6">
          {[
            { value: "day" as const, label: "Last Day" },
            { value: "week" as const, label: "Last Week" },
            { value: "month" as const, label: "Monthly" },
            { value: "year" as const, label: "Yearly" },
          ].map((filter) => (
            <button
              key={filter.value}
              onClick={() => setTimeFilter(filter.value)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                timeFilter === filter.value
                  ? " !bg-[var(--button-primary)] hover:!bg-[var(--button-primary-hover)] disabled:!bg-[var(--button-primary-disabled)] text-primary-foreground"
                  : "bg-muted hover:bg-muted/80"
              }`}
            >
              {t(filter.label)}
            </button>
          ))}
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
          {stats.map((stat, idx) => (
            <div
              key={idx}
              className="rounded-xl border bg-card p-6 hover:shadow-lg transition-shadow"
            >
              <div className="flex flex-col items-center text-center">
                <div className={`p-3 rounded-lg ${stat.bgColor} mb-4`}>
                  <stat.icon className={`h-6 w-6 ${stat.color}`} />
                </div>
                <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
                  {t(stat.label)}
                </div>
                <div className="text-4xl font-bold mb-3">{stat.value}</div>
                <div className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${stat.changePositive ? "bg-green-500/10 text-green-600" : "bg-red-500/10 text-red-600"}`}>
                  <TrendingUp className={`h-3 w-3 ${stat.changePositive ? "" : "rotate-180"}`} />
                  {t(stat.change)}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Charts Row */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
          {/* API Requests Line Chart */}
          <div className="rounded-xl border bg-card p-6">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h3 className="text-lg font-semibold mb-1">{t("API Requests")}</h3>
                <p className="text-sm text-muted-foreground">
                  {t("Total requests over time")}
                </p>
              </div>
              <Activity className="h-5 w-5 text-purple-500" />
            </div>

            <div className="h-64 relative">
              {/* Grid lines */}
              <div className="absolute inset-0 flex flex-col justify-between pb-6">
                {[0, 1, 2, 3, 4].map((i) => (
                  <div key={i} className="border-t border-muted/30" />
                ))}
              </div>
              
              {/* Chart Container */}
              <div className="absolute inset-0 pb-6">
                <svg className="w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none">
                  {/* Gradient definition */}
                  <defs>
                    <linearGradient id="areaGradient" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="rgb(168, 85, 247)" stopOpacity="0.4" />
                      <stop offset="100%" stopColor="rgb(168, 85, 247)" stopOpacity="0.0" />
                    </linearGradient>
                  </defs>
                  
                  {/* Area fill */}
                  <path
                    d={(() => {
                      const maxRequests = Math.max(...performanceData.map(d => d.requests));
                      const pathData = performanceData.map((d, i) => {
                        const x = (i / (performanceData.length - 1)) * 100;
                        const y = 100 - ((d.requests / maxRequests) * 85);
                        return i === 0 ? `M ${x} ${y}` : `L ${x} ${y}`;
                      }).join(' ');
                      return `${pathData} L 100 100 L 0 100 Z`;
                    })()}
                    fill="url(#areaGradient)"
                  />
                  
                  {/* Line */}
                  <polyline
                    fill="none"
                    stroke="rgb(168, 85, 247)"
                    strokeWidth="0.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    points={performanceData.map((d, i) => {
                      const x = (i / (performanceData.length - 1)) * 100;
                      const maxRequests = Math.max(...performanceData.map(d => d.requests));
                      const y = 100 - ((d.requests / maxRequests) * 85);
                      return `${x},${y}`;
                    }).join(' ')}
                  />
                  
                  {/* Data points */}
                  {performanceData.map((d, i) => {
                    const x = (i / (performanceData.length - 1)) * 100;
                    const maxRequests = Math.max(...performanceData.map(d => d.requests));
                    const y = 100 - ((d.requests / maxRequests) * 85);
                    return (
                      <g key={`point-${i}`}>
                        <circle
                          cx={x}
                          cy={y}
                          r="1.2"
                          fill="rgb(168, 85, 247)"
                          className="cursor-pointer"
                        />
                        <circle
                          cx={x}
                          cy={y}
                          r="3"
                          fill="transparent"
                          className="cursor-pointer"
                        >
                          <title>{`${t(d.label)}: ${d.requests.toLocaleString()} ${t("requests")}`}</title>
                        </circle>
                      </g>
                    );
                  })}
                </svg>
              </div>
              
              {/* X-axis labels */}
              <div className="absolute bottom-0 left-0 right-0 flex justify-between px-2">
                {performanceData.map((d, i) => (
                  <span key={i} className="text-xs text-muted-foreground">
                    {t(d.label)}
                  </span>
                ))}
              </div>
            </div>
            
            {/* Stats */}
            <div className="flex items-center justify-between mt-6 pt-4 border-t">
              <div>
                <div className="text-2xl font-bold">
                  {Math.max(...performanceData.map(d => d.requests)).toLocaleString()}
                </div>
                <div className="text-xs text-muted-foreground">{t("Peak requests")}</div>
              </div>
              <div>
                <div className="text-2xl font-bold">
                  {Math.round(performanceData.reduce((sum, d) => sum + d.requests, 0) / performanceData.length).toLocaleString()}
                </div>
                <div className="text-xs text-muted-foreground">{t("Average")}</div>
              </div>
            </div>
          </div>

          {/* Workagent Executions Bar Chart */}
          <div className="rounded-xl border bg-card p-6">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h3 className="text-lg font-semibold mb-1">{t("Workagent Executions")}</h3>
                <p className="text-sm text-muted-foreground">
                  {t("Completed workflows over time")}
                </p>
              </div>
              <TrendingUp className="h-5 w-5 text-blue-500" />
            </div>

            <div className="h-64 relative">
              {/* Grid lines */}
              <div className="absolute inset-0 flex flex-col justify-between pb-6">
                {[0, 1, 2, 3, 4].map((i) => (
                  <div key={i} className="border-t border-muted/30" />
                ))}
              </div>
              
              {/* Chart Container */}
              <div className="absolute inset-0 pb-6">
                <svg className="w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none">
                  {/* Bars */}
                  {performanceData.map((d, i) => {
                    const maxExecutions = Math.max(...performanceData.map(d => d.executions));
                    const barHeight = (d.executions / maxExecutions) * 85;
                    const barWidth = 100 / performanceData.length;
                    const x = (i * barWidth) + (barWidth * 0.2);
                    const width = barWidth * 0.6;
                    
                    return (
                      <g key={`bar-${i}`}>
                        <rect
                          x={x}
                          y={100 - barHeight}
                          width={width}
                          height={barHeight}
                          fill="rgb(59, 130, 246)"
                          rx="1"
                          className="hover:opacity-80 transition-opacity cursor-pointer"
                        />
                        <rect
                          x={x}
                          y={100 - barHeight}
                          width={width}
                          height={barHeight}
                          fill="transparent"
                          className="cursor-pointer"
                        >
                          <title>{`${t(d.label)}: ${d.executions.toLocaleString()} ${t("executions")}`}</title>
                        </rect>
                      </g>
                    );
                  })}
                </svg>
              </div>
              
              {/* X-axis labels */}
              <div className="absolute bottom-0 left-0 right-0 flex justify-between px-2">
                {performanceData.map((d, i) => (
                  <span key={i} className="text-xs text-muted-foreground">
                    {t(d.label)}
                  </span>
                ))}
              </div>
            </div>
            
            {/* Stats */}
            <div className="flex items-center justify-between mt-6 pt-4 border-t">
              <div>
                <div className="text-2xl font-bold">
                  {Math.max(...performanceData.map(d => d.executions)).toLocaleString()}
                </div>
                <div className="text-xs text-muted-foreground">{t("Peak executions")}</div>
              </div>
              <div>
                <div className="text-2xl font-bold">
                  {Math.round(performanceData.reduce((sum, d) => sum + d.executions, 0) / performanceData.length).toLocaleString()}
                </div>
                <div className="text-xs text-muted-foreground">{t("Average")}</div>
              </div>
            </div>
          </div>

          {/* Project Status Donut Chart */}
          <div className="rounded-xl border bg-card p-6">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h3 className="text-lg font-semibold mb-1">{t("Project Status")}</h3>
                <p className="text-sm text-muted-foreground">{t("Distribution by state")}</p>
              </div>
            </div>
            <div className="flex items-center justify-center mb-6">
              <div className="relative w-48 h-48">
                <svg viewBox="0 0 200 200" className="transform -rotate-90">
                  {projectStatus.map((item, idx) => {
                    const prevTotal = projectStatus
                      .slice(0, idx)
                      .reduce((sum, i) => sum + i.value, 0);
                    const percentage = (item.value / total) * 100;
                    const offset = (prevTotal / total) * 100;
                    return (
                      <circle
                        key={idx}
                        cx="100"
                        cy="100"
                        r="80"
                        fill="none"
                        stroke={`hsl(${idx * 60 + 270}, 70%, 55%)`}
                        strokeWidth="24"
                        strokeDasharray={`${percentage * 5.024} 502.4`}
                        strokeDashoffset={-offset * 5.024}
                        className="transition-all duration-300"
                      />
                    );
                  })}
                </svg>
              </div>
            </div>
            <div className="space-y-3">
              {projectStatus.map((item, idx) => (
                <div key={idx} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className={`w-3 h-3 rounded-full ${item.color}`} />
                    <span className="text-sm">{t(item.label)}</span>
                  </div>
                  <span className="text-sm font-semibold">{item.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Recent Projects */}
        <div className="rounded-xl border bg-card p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-lg font-semibold mb-1">{t("Recent Projects")}</h3>
              <p className="text-sm text-muted-foreground">{t("Your most active workflows")}</p>
            </div>
            <Button variant="ghost" size="sm" className="text-primary">
              {t("View all")} <ArrowUpRight className="ml-1 h-4 w-4" />
            </Button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {recentProjects.map((project) => (
              <div
                key={project.id}
                className="flex items-center gap-4 p-4 rounded-lg border hover:border-primary/50 transition-colors cursor-pointer"
              >
                
                <div className="flex-1 min-w-0">
                  <h4 className="font-semibold truncate">{t(project.name)}</h4>
                  <p className="text-xs text-muted-foreground">{t(project.type)}</p>
                  <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
                    <span>{t("Executions:")} {project.executions}</span>
                    <span>{t("Last edited:")} {project.lastEdited}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`px-2 py-1 rounded text-xs font-medium ${
                      project.status === "Active"
                        ? "bg-green-500/10 text-green-500"
                        : "bg-orange-500/10 text-orange-500"
                    }`}
                  >
                    {t(project.status)}
                  </span>
                  <ArrowUpRight className="h-4 w-4 text-muted-foreground" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
