const SIDEBAR_CATEGORY_ACCENTS: Record<string, string> = {
  input_output: "#2563eb",
  agents: "#16a34a",
  mcp: "#0ea5e9",
  models: "#c026d3",
  vectorstores: "#ca8a04",
  processing: "#475569",
  logic: "#64748b",
  tools: "#06b6d4",
  Guardrails: "#6b7280",
  HumanInTheLoop: "#6b7280",
  outputs: "#dc2626",
  prompts: "#7c3aed",
  chains: "#f97316",
  helpers: "#0ea5e9",
};

export const getCategoryAccentColor = (
  categoryName: string,
  nodeColors: Record<string, string>,
) => {
  return SIDEBAR_CATEGORY_ACCENTS[categoryName] ?? nodeColors[categoryName] ?? "#2563eb";
};

