// TARGET PATH: src/frontend/src/CustomNodes/A2ANode/index.tsx
import { Handle, Position, useUpdateNodeInternals } from "@xyflow/react";
import { memo, useCallback, useEffect, useMemo, useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import useAgentStore from "@/stores/agentStore";
import type { NodeDataType } from "@/types/agent";
import { cn } from "@/utils/utils";

interface A2AAgentConfig {
  id: string;
  num: number; // 1, 2, 3, 4 - corresponds to agent_1_*, agent_2_*, etc.
  name: string;
  prompt: string;
  enabled: boolean;
}

interface A2ANodeProps {
  data: NodeDataType;
  selected?: boolean;
}

const A2A_NODE_COLOR = "#6366F1";
const MAX_AGENTS = 4;

function A2ANode({ data, selected }: A2ANodeProps) {
  const updateNodeInternals = useUpdateNodeInternals();
  const setNode = useAgentStore((state) => state.setNode);

  // Initialize agents from the backend's fixed template values
  const initialAgents: A2AAgentConfig[] = useMemo(() => {
    const template = data.node?.template;
    const agents: A2AAgentConfig[] = [];

    // Agent 1 (always enabled)
    agents.push({
      id: "agent-1",
      num: 1,
      name: template?.agent_1_name?.value ?? "Agent 1",
      prompt:
        template?.agent_1_instructions?.value ??
        "You are a helpful assistant that analyzes the input and provides insights.",
      enabled: true,
    });

    // Agent 2 (always enabled)
    agents.push({
      id: "agent-2",
      num: 2,
      name: template?.agent_2_name?.value ?? "Agent 2",
      prompt:
        template?.agent_2_instructions?.value ??
        "You are a research assistant that expands on the previous analysis.",
      enabled: true,
    });

    // Agent 3 (optional)
    if (template?.enable_agent_3?.value) {
      agents.push({
        id: "agent-3",
        num: 3,
        name: template?.agent_3_name?.value ?? "Agent 3",
        prompt:
          template?.agent_3_instructions?.value ??
          "You are a reviewer that refines and improves the output.",
        enabled: true,
      });
    }

    // Agent 4 (optional)
    if (template?.enable_agent_4?.value) {
      agents.push({
        id: "agent-4",
        num: 4,
        name: template?.agent_4_name?.value ?? "Agent 4",
        prompt:
          template?.agent_4_instructions?.value ??
          "You are a final editor that produces the polished output.",
        enabled: true,
      });
    }

    return agents;
  }, [data.node?.template]);

  const [agents, setAgents] = useState<A2AAgentConfig[]>(initialAgents);

  // Sync with template changes
  useEffect(() => {
    setAgents(initialAgents);
  }, [initialAgents]);

  // Update the backend template when agents change
  const updateNodeTemplate = useCallback(
    (agentNum: number, field: "name" | "instructions" | "enabled", value: string | boolean) => {
      setNode(data.id, (node) => {
        const template = { ...node.data.node?.template };

        if (field === "enabled") {
          // Enable/disable agent 3 or 4
          if (agentNum === 3) {
            template.enable_agent_3 = { ...template.enable_agent_3, value };
          } else if (agentNum === 4) {
            template.enable_agent_4 = { ...template.enable_agent_4, value };
          }
        } else if (field === "name") {
          const key = `agent_${agentNum}_name`;
          template[key] = { ...template[key], value };
        } else if (field === "instructions") {
          const key = `agent_${agentNum}_instructions`;
          template[key] = { ...template[key], value };
        }

        return {
          ...node,
          data: {
            ...node.data,
            node: {
              ...node.data.node,
              template,
            },
          },
        };
      });
    },
    [data.id, setNode],
  );

  const addAgent = useCallback(() => {
    // Find the next available agent slot (3 or 4)
    const existingNums = agents.map((a) => a.num);
    let nextNum: number | null = null;

    for (let i = 3; i <= MAX_AGENTS; i++) {
      if (!existingNums.includes(i)) {
        nextNum = i;
        break;
      }
    }

    if (nextNum === null) {
      return; // Max agents reached
    }

    const defaultPrompts: Record<number, string> = {
      3: "You are a reviewer that refines and improves the output.",
      4: "You are a final editor that produces the polished output.",
    };

    const newAgent: A2AAgentConfig = {
      id: `agent-${nextNum}`,
      num: nextNum,
      name: `Agent ${nextNum}`,
      prompt: defaultPrompts[nextNum] || "",
      enabled: true,
    };

    // Enable the agent in the template
    updateNodeTemplate(nextNum, "enabled", true);

    const newAgents = [...agents, newAgent].sort((a, b) => a.num - b.num);
    setAgents(newAgents);

    // Update handles after adding agent
    setTimeout(() => updateNodeInternals(data.id), 50);
  }, [agents, data.id, updateNodeInternals, updateNodeTemplate]);

  const removeAgent = useCallback(
    (agentNum: number) => {
      if (agentNum <= 2) {
        return; // Cannot remove first two agents
      }

      // Disable the agent in the template
      updateNodeTemplate(agentNum, "enabled", false);

      const newAgents = agents.filter((a) => a.num !== agentNum);
      setAgents(newAgents);

      // Update handles after removing agent
      setTimeout(() => updateNodeInternals(data.id), 50);
    },
    [agents, data.id, updateNodeInternals, updateNodeTemplate],
  );

  const updateAgent = useCallback(
    (agentNum: number, field: "name" | "prompt", value: string) => {
      const newAgents = agents.map((a) =>
        a.num === agentNum ? { ...a, [field]: value } : a,
      );
      setAgents(newAgents);

      // Map prompt to instructions for the template
      const templateField = field === "prompt" ? "instructions" : field;
      updateNodeTemplate(agentNum, templateField, value);
    },
    [agents, updateNodeTemplate],
  );

  // Update internals when component mounts or agents change
  useEffect(() => {
    updateNodeInternals(data.id);
  }, [data.id, updateNodeInternals, agents.length]);

  const canAddAgent = agents.length < MAX_AGENTS;

  return (
    <div
      className={cn(
        "w-[400px] rounded-xl border shadow-sm bg-background",
        selected && "ring-2 ring-primary",
      )}
      style={{ borderColor: A2A_NODE_COLOR }}
    >
      {/* Input Handle - for task/message input */}
      <Handle
        type="target"
        position={Position.Left}
        id="task"
        style={{
          width: 12,
          height: 12,
          background: A2A_NODE_COLOR,
          border: "2px solid white",
          top: 28,
        }}
      />

      {/* Header */}
      <div
        className="flex items-center justify-between p-3 border-b rounded-t-xl"
        style={{ backgroundColor: `${A2A_NODE_COLOR}15` }}
      >
        <div className="flex items-center gap-2">
          <div
            className="p-1.5 rounded-md"
            style={{ backgroundColor: A2A_NODE_COLOR }}
          >
            <ForwardedIconComponent
              name="Network"
              className="h-4 w-4 text-white"
            />
          </div>
          <div>
            <span className="font-semibold text-sm">A2A Agents</span>
            <p className="text-xs text-muted-foreground">
              Google A2A Protocol
            </p>
          </div>
        </div>
        {canAddAgent && (
          <Button
            size="sm"
            variant="ghost"
            onClick={addAgent}
            className="h-8 w-8 p-0"
            title="Add Agent"
          >
            <ForwardedIconComponent name="Plus" className="h-4 w-4" />
          </Button>
        )}
      </div>

      {/* Agents List */}
      <div className="p-3 space-y-3 max-h-[500px] overflow-y-auto">
        {agents.map((agent, index) => (
          <div
            key={agent.id}
            className="relative p-3 border rounded-lg bg-muted/30"
          >
            {/* Agent LLM Handle - uses backend naming convention */}
            <Handle
              type="target"
              position={Position.Left}
              id={`agent_${agent.num}_llm`}
              style={{
                width: 10,
                height: 10,
                background: "#F97316",
                border: "2px solid white",
                top: 85 + index * 180,
                left: -5,
              }}
            />

            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2 flex-1">
                <div
                  className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium text-white"
                  style={{ backgroundColor: A2A_NODE_COLOR }}
                >
                  {agent.num}
                </div>
                <Input
                  value={agent.name}
                  onChange={(e) => updateAgent(agent.num, "name", e.target.value)}
                  placeholder="Agent Name"
                  className="flex-1 h-8 text-sm font-medium"
                />
              </div>
              {agent.num > 2 && (
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => removeAgent(agent.num)}
                  className="h-7 w-7 ml-2 text-muted-foreground hover:text-destructive"
                >
                  <ForwardedIconComponent name="Trash2" className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>

            <Textarea
              value={agent.prompt}
              onChange={(e) => updateAgent(agent.num, "prompt", e.target.value)}
              placeholder="System prompt / instructions for this agent..."
              rows={3}
              className="text-sm resize-none"
            />

            <div className="flex items-center gap-1 mt-2 text-xs text-muted-foreground">
              <ForwardedIconComponent name="Cpu" className="h-3 w-3" />
              <span>Connect LLM →</span>
            </div>

            {/* Arrow to next agent */}
            {index < agents.length - 1 && (
              <div className="flex justify-center py-2 -mb-5">
                <div className="flex flex-col items-center">
                  <div
                    className="w-0.5 h-4"
                    style={{ backgroundColor: A2A_NODE_COLOR }}
                  />
                  <ForwardedIconComponent
                    name="ChevronDown"
                    className="h-4 w-4"
                    style={{ color: A2A_NODE_COLOR }}
                  />
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="p-3 border-t bg-muted/30 rounded-b-xl">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <ForwardedIconComponent name="ArrowRightLeft" className="h-3 w-3" />
            <span>Sequential Communication</span>
          </div>
          <span>{agents.length} agents</span>
        </div>
      </div>

      {/* Output Handle - for response output */}
      <Handle
        type="source"
        position={Position.Right}
        id="response"
        style={{
          width: 12,
          height: 12,
          background: A2A_NODE_COLOR,
          border: "2px solid white",
          bottom: 28,
          top: "auto",
        }}
      />
    </div>
  );
}

export default memo(A2ANode);
