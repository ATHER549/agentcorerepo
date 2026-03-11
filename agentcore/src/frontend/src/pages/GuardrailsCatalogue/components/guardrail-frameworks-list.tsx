import { ArrowRight, Shield, Zap, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";

interface GuardrailFramework {
  id: string;
  name: string;
  description: string;
  icon?: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  rulesCount?: number;
}

interface GuardrailFrameworksListProps {
  frameworks: GuardrailFramework[];
  onSelectFramework: (framework: GuardrailFramework) => void;
  isLoading?: boolean;
}

export default function GuardrailFrameworksList({
  frameworks,
  onSelectFramework,
  isLoading = false,
}: GuardrailFrameworksListProps): JSX.Element {
  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* Header Section */}
      <div className="relative flex flex-shrink-0 items-center justify-between border-b border-border/50 px-8 py-8">
        {/* Decorative line with red accent */}
        <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-red-500/30 to-transparent" />
        
        <div>
          <div className="mb-3 flex items-center gap-4">
            
            <h1 className="text-3xl font-bold text-foreground">
              Guardrails Catalogue
            </h1>
          </div>
          <p className="text-sm text-muted-foreground/90">
            Choose a security framework to configure and manage AI safety policies
          </p>
        </div>
      </div>

      {/* Content Section */}
      <div className="flex-1 overflow-auto px-8 py-10">
        {isLoading ? (
          <div className="flex h-full w-full items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <div className="h-12 w-12 animate-spin rounded-full border-4 border-border border-t-red-500" />
              <p className="text-sm text-muted-foreground">Loading frameworks...</p>
            </div>
          </div>
        ) : frameworks.length === 0 ? (
          <div className="flex h-full w-full items-center justify-center">
            <div className="text-center">
              <Lock className="mx-auto mb-4 h-12 w-12 text-muted-foreground/40" />
              <p className="text-lg font-medium text-foreground">No frameworks available</p>
              <p className="mt-2 text-sm text-muted-foreground">
                Check back soon for more guardrail options
              </p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            {frameworks.map((framework) => (
              <div
                key={framework.id}
                className="group relative h-full overflow-hidden rounded-2xl border border-border/60 bg-card transition-all duration-300 hover:border-red-500/40 hover:shadow-lg hover:shadow-red-500/10"
              >
                {/* Top accent bar on hover - red gradient */}
                <div className="absolute top-0 left-0 right-0 h-1.5 bg-gradient-to-r from-red-500 via-red-400 to-red-500/60 opacity-0 transition-opacity duration-300 group-hover:opacity-100" />

                {/* Content */}
                <div className="relative flex flex-col justify-between h-full p-6">
                  {/* Icon and Header */}
                  <div>
                    {framework.icon && (
                      <div className="mb-4 inline-flex h-14 w-14 items-center justify-center rounded-xl bg-red-500/10 p-3 ring-1 ring-red-500/20 transition-all duration-300 group-hover:bg-red-500/15 group-hover:ring-red-500/40 group-hover:shadow-lg group-hover:shadow-red-500/20">
                        <framework.icon className="h-full w-full text-red-600 dark:text-red-400" />
                      </div>
                    )}

                    <h3 className="mb-2 text-lg font-bold text-foreground">
                      {framework.name}
                    </h3>

                    <p className="mb-4 text-sm leading-relaxed text-muted-foreground/90">
                      {framework.description}
                    </p>

                    {/* Stats Badge */}
                    {framework.rulesCount !== undefined && (
                      <div className="mb-4 flex items-center gap-2 rounded-lg bg-red-500/10 px-3 py-2 ring-1 ring-inset ring-red-500/30">
                        <Zap className="h-4 w-4 text-red-600 dark:text-red-400" />
                        <span className="text-xs font-semibold text-foreground">
                          {framework.rulesCount} policies
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Action Button */}
                  <Button
                    onClick={() => onSelectFramework(framework)}
                    className="relative mt-4 w-full gap-2 overflow-hidden font-semibold transition-all duration-300 hover:shadow-lg hover:shadow-red-500/20 active:scale-95 hover:border-red-500/50"
                  >
                    <span>View Policies</span>
                    <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" />
                  </Button>

                  {/* Hover indicator line at bottom - red accent */}
                  <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-red-500/40 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
