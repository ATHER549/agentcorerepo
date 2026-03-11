/**
 * ApprovalPage Types and Interfaces
 * 
 * Defines all TypeScript interfaces used in the ApprovalPage
 */

/**
 * Represents an agent awaiting approval
 */
export interface ApprovalAgent {
  id: string;
  title: string;
  status: "pending" | "approved" | "rejected";
  description: string;
  submittedBy: {
    name: string;
    avatar?: string;
  };
  project: string;
  submitted: string;
  version: string;
  recentChanges: string;
}

/**
 * Data sent to the ActionModal for approval/rejection
 */
export interface ApprovalActionData {
  comments: string;
  attachments: File[];
}

/**
 * API request parameters for approving an agent
 */
export interface ApproveAgentRequest {
  agentId: string;
  comments: string;
}

/**
 * API request parameters for rejecting an agent
 */
export interface RejectAgentRequest {
  agentId: string;
  comments: string;
  reason?: string;
}

/**
 * API response from approval endpoints
 */
export interface ApprovalResponse {
  success: boolean;
  message: string;
  agentId: string;
  newStatus: "approved" | "rejected";
  timestamp: string;
}

/**
 * Modal state for approval actions
 */
export interface ApprovalModalState {
  isOpen: boolean;
  selectedAgent: ApprovalAgent | null;
  action: "approve" | "reject";
}

/**
 * Filter options for agents
 */
export type ApprovalFilterType = "all" | "pending" | "approved" | "rejected";

/**
 * Count statistics for filtered agents
 */
export interface ApprovalCounts {
  all: number;
  pending: number;
  approved: number;
  rejected: number;
}
