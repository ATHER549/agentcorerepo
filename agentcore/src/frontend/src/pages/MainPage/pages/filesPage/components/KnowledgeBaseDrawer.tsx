import { useContext, useEffect, useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AuthContext } from "@/contexts/authContext";
import type {
  KBVisibility,
  KnowledgeBaseInfo,
} from "@/controllers/API/queries/knowledge-bases/use-get-knowledge-bases";
import { useUpdateKBVisibility } from "@/controllers/API/queries/knowledge-bases/use-update-kb-visibility";
import useAlertStore from "@/stores/alertStore";

interface KnowledgeBaseDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  knowledgeBase: KnowledgeBaseInfo | null;
}

const VISIBILITY_LABELS: Record<KBVisibility, string> = {
  PRIVATE: "Private - Only you",
  DEPARTMENT: "Department - Your departments",
  ORGANIZATION: "Organization - Everyone in org",
};

const KnowledgeBaseDrawer = ({
  isOpen,
  onClose,
  knowledgeBase,
}: KnowledgeBaseDrawerProps) => {
  const { userData, role } = useContext(AuthContext);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const [selectedVisibility, setSelectedVisibility] = useState<KBVisibility>(
    knowledgeBase?.visibility || "PRIVATE",
  );

  useEffect(() => {
    setSelectedVisibility(knowledgeBase?.visibility || "PRIVATE");
  }, [knowledgeBase?.id]);

  const isOwner = knowledgeBase?.created_by === userData?.id;
  const isAdmin = ["root", "super_admin", "department_admin"].includes(
    (role || "").toLowerCase(),
  );
  const canEditVisibility = isOwner || isAdmin;

  const updateVisibilityMutation = useUpdateKBVisibility(
    { kb_id: knowledgeBase?.id || "" },
    {
      onError: (error: any) => {
        setSelectedVisibility(knowledgeBase?.visibility || "PRIVATE");
        setErrorData({
          title: "Failed to update visibility",
          list: [error?.response?.data?.detail || "Unexpected error"],
        });
      },
    },
  );

  const handleVisibilityChange = (value: KBVisibility) => {
    setSelectedVisibility(value);
    updateVisibilityMutation.mutate({ visibility: value });
  };

  if (!isOpen || !knowledgeBase) {
    return null;
  }

  return (
    <div className="flex h-full w-80 flex-col border-l bg-background">
      <div className="flex items-center justify-between px-4 pt-4">
        <h3 className="font-semibold">{knowledgeBase.name}</h3>
        <Button variant="ghost" size="iconSm" onClick={onClose}>
          <ForwardedIconComponent name="X" className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto pt-3">
        <div className="flex flex-col gap-4">
          <div className="space-y-2 px-4">
            <label className="text-sm font-medium">Visibility</label>
            {canEditVisibility ? (
              <Select
                value={selectedVisibility}
                onValueChange={handleVisibilityChange}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select visibility" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="PRIVATE">
                    Private - Only you
                  </SelectItem>
                  <SelectItem value="DEPARTMENT">
                    Department - Your departments
                  </SelectItem>
                  <SelectItem value="ORGANIZATION">
                    Organization - Everyone in org
                  </SelectItem>
                </SelectContent>
              </Select>
            ) : (
              <div className="text-sm text-muted-foreground">
                {VISIBILITY_LABELS[selectedVisibility] || selectedVisibility}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default KnowledgeBaseDrawer;
