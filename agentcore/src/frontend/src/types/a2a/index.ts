// TARGET PATH: src/frontend/src/types/a2a/index.ts
// A2A (Agent-to-Agent) Protocol Types - Google A2A Standard

export interface A2AAgentConfig {
  id: string;
  name: string;
  prompt: string;
  llmHandleId?: string;
}

export interface A2ANodeData {
  agents: A2AAgentConfig[];
  communicationMode: "sequential";
}

// Google A2A Protocol types
export interface A2AAgentCard {
  name: string;
  description: string;
  capabilities: string[];
  endpoint?: string;
}

export interface A2ATask {
  id: string;
  input: string;
  expectedOutput?: string;
  status: "pending" | "running" | "completed" | "failed";
}

export interface A2AMessage {
  id: string;
  taskId: string;
  senderId: string;
  receiverId: string;
  content: string;
  messageType: "request" | "response" | "error";
  timestamp: string;
  artifacts?: Record<string, any>;
}

export interface A2AConversationLog {
  groupId: string;
  messages: A2AMessage[];
  startTime: string;
  endTime?: string;
  status: "running" | "completed" | "error";
}

export interface A2AComponentType {
  id: string;
  name: string;
  display_name: string;
  description: string;
  icon: string;
  agents: A2AAgentConfig[];
}
