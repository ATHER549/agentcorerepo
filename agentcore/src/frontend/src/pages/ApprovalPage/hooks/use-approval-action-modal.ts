import { useCallback, useState } from "react";
import type { ApprovalAgent } from "@/controllers/API/queries/approvals";

/**
 * Custom hook to manage approval action modal state
 * Handles opening/closing modal and tracking which agent is being reviewed
 */
export const useApprovalActionModal = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<ApprovalAgent | null>(null);
  const [action, setAction] = useState<"approve" | "reject">("approve");

  const openModal = useCallback(
    (agent: ApprovalAgent, actionType: "approve" | "reject") => {
      setSelectedAgent(agent);
      setAction(actionType);
      setIsOpen(true);
    },
    [],
  );

  const closeModal = useCallback(() => {
    setIsOpen(false);
    // Clear selection after modal closes
    setTimeout(() => {
      setSelectedAgent(null);
    }, 300);
  }, []);

  return {
    isOpen,
    selectedAgent,
    action,
    openModal,
    closeModal,
  };
};
