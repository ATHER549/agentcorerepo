import { fireEvent, render, screen } from "@testing-library/react";
import MenuBar from "../index";

jest.mock("@/components/ui/button", () => ({
  Button: ({ children, ...rest }) => <button {...rest}>{children}</button>,
}));
jest.mock("@/components/common/genericIconComponent", () => ({
  __esModule: true,
  default: ({ name }) => <span data-testid="icon">{name}</span>,
}));
jest.mock("@/components/common/shadTooltipComponent", () => ({
  __esModule: true,
  default: ({ children }) => <div>{children}</div>,
}));
jest.mock("@/components/core/agentSettingsComponent", () => ({
  __esModule: true,
  default: () => <div data-testid="agent-settings" />,
}));
jest.mock(
  "@/controllers/API/queries/agents/use-get-refresh-agents-query",
  () => ({ __esModule: true, useGetRefreshAgentsQuery: () => ({}) }),
);
jest.mock("@/controllers/API/queries/folders/use-get-folders", () => ({
  __esModule: true,
  useGetFoldersQuery: () => ({
    data: [{ id: "f1", name: "Folder" }],
    isFetched: true,
  }),
}));
const mockSave = jest.fn(() => Promise.resolve());
jest.mock("@/hooks/agents/use-save-agent", () => ({
  __esModule: true,
  default: () => mockSave,
}));
jest.mock("@/hooks/use-unsaved-changes", () => ({
  __esModule: true,
  useUnsavedChanges: () => true,
}));
jest.mock("@/customization/hooks/use-custom-navigate", () => ({
  __esModule: true,
  useCustomNavigate: () => jest.fn(),
}));
jest.mock("@/stores/agentsManagerStore", () => ({
  __esModule: true,
  default: (sel) =>
    sel({
      autoSaving: false,
      saveLoading: false,
      currentAgent: { updated_at: new Date().toISOString() },
    }),
}));
jest.mock("@/stores/alertStore", () => ({
  __esModule: true,
  default: (sel) => sel({ setSuccessData: jest.fn() }),
}));
jest.mock("@/stores/agentStore", () => ({
  __esModule: true,
  default: (sel) =>
    sel({
      onAgentBuilderPage: true,
      isBuilding: false,
      currentAgent: {
        id: "1",
        name: "agent",
        project_id: "f1",
        icon: "Workagent",
        gradient: "0",
        locked: false,
      },
    }),
}));
jest.mock("@/stores/shortcuts", () => ({
  __esModule: true,
  useShortcutsStore: (sel) => sel({ changesSave: "mod+s" }),
}));

// Avoid pulling utils that depend on darkStore
jest.mock("@/utils/utils", () => ({
  __esModule: true,
  cn: (...args) => args.filter(Boolean).join(" "),
  getNumberFromString: () => 0,
}));

// styleUtils imports lucide dynamic icons; stub to avoid resolution
jest.mock("lucide-react/dynamicIconImports", () => ({}), { virtual: true });

describe("AgentMenu MenuBar", () => {
  it("renders current folder and agent name, enables save", async () => {
    render(<MenuBar />);
    expect(screen.getByTestId("menu_bar_wrapper")).toBeInTheDocument();
    expect(screen.getByText("Folder")).toBeInTheDocument();
    expect(screen.getByTestId("agent_name").textContent).toBe("agent");

    const saveBtn = screen.getByTestId("save-agent-button");
    expect(saveBtn).not.toBeDisabled();
  });

  it("clicking save calls save agent", () => {
    mockSave.mockClear();
    render(<MenuBar />);
    fireEvent.click(screen.getByTestId("save-agent-button"));
    expect(mockSave).toHaveBeenCalled();
  });
});
