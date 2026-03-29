import { Button } from "@/src/components/ui/button";
import { cn } from "@/src/utils/tailwind";
import React from "react";

interface AuthProviderButtonProps {
  icon: React.ReactNode;
  label: string;
  onClick?: () => void;
  loading?: boolean;
  showLastUsedBadge?: boolean;
  prominent?: boolean;
}

export function AuthProviderButton({
  icon,
  label,
  onClick,
  loading = false,
  showLastUsedBadge = false,
  prominent = false,
}: AuthProviderButtonProps) {
  return (
    <div className="w-full">
      <Button
        onClick={onClick}
        variant={prominent ? "default" : "secondary"}
        loading={loading}
        className={cn(
          "w-full",
          prominent &&
            "bg-red-600 py-6 text-base text-white shadow-md hover:bg-red-700",
        )}
      >
        {icon}
        {label}
      </Button>
      <div
        className={cn(
          "text-muted-foreground mt-0.5 text-center text-xs",
          showLastUsedBadge ? "visible" : "invisible",
        )}
      >
        Last used
      </div>
    </div>
  );
}
