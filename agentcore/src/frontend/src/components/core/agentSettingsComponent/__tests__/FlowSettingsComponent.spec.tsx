import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import AgentSettingsComponent from "../index";

jest.mock("@/components/ui/button", () => ({
  Button: ({ children, loading, ...rest }) => (
    <button {...rest}>{children}</button>
  ),
}));

// Simplify Radix Form to a native form that respects onSubmit
jest.mock("@radix-ui/react-form", () => ({
  __esModule: true,
  Root: React.forwardRef<HTMLFormElement, any>(
    ({ children, onSubmit }, ref) => (
      <form onSubmit={onSubmit} ref={ref}>
        {children}
      </form>
    ),
  ),
  Submit: ({ asChild, children }) => {
    if (asChild && React.isValidElement(children)) {
      return React.cloneElement(children as any, { type: "submit" });
    }
    return <button type="submit">Submit</button>;
  },
}));

const mockSave = jest.fn();
jest.mock("@/hooks/agents/use-save-agent", () => ({
  __esModule: true,
  default: () => mockSave,
}));

let mockSetSuccessData = jest.fn();
jest.mock("@/stores/alertStore", () => ({
  __esModule: true,
  default: (sel) => sel({ setSuccessData: mockSetSuccessData }),
}));

let mockSetCurrentAgent = jest.fn();
jest.mock("@/stores/agentStore", () => ({
  __esModule: true,
  default: (sel) =>
    sel({
      currentAgent: {
        id: "1",
        name: "agent",
        description: "Desc",
        locked: false,
      },
      setCurrentAgent: mockSetCurrentAgent,
    }),
}));

let mockAutoSaving = false;
let mockAgents: Array<{ name: string }> = [];
jest.mock("@/stores/agentsManagerStore", () => ({
  __esModule: true,
  default: (sel) => sel({ autoSaving: mockAutoSaving, agents: mockAgents }),
}));

// Mock EditAgentSettings to expose simple controls that call the provided setters
jest.mock("@/components/core/editAgentSettingsComponent", () => ({
  __esModule: true,
  default: ({
    setName,
    setDescription,
    setLocked,
  }: {
    setName?: (v: string) => void;
    setDescription?: (v: string) => void;
    setLocked?: (v: boolean) => void;
  }) => (
    <div>
      <button data-testid="set-name-new" onClick={() => setName?.("New Name")}>
        set name
      </button>
      <button data-testid="set-name-taken" onClick={() => setName?.("Taken")}>
        set taken
      </button>
      <button
        data-testid="set-desc-new"
        onClick={() => setDescription?.("New Desc")}
      >
        set desc
      </button>
      <button data-testid="toggle-lock" onClick={() => setLocked?.(true)}>
        toggle lock
      </button>
    </div>
  ),
}));

describe("AgentSettingsComponent", () => {
  const baseAgent = {
    id: "1",
    name: "agent",
    description: "Desc",
    locked: false,
  } as any;

  beforeEach(() => {
    jest.clearAllMocks();
    mockAutoSaving = false;
    mockAgents = [{ name: "agent" }, { name: "Other" }];
    mockSetSuccessData = jest.fn();
    mockSetCurrentAgent = jest.fn();
  });

  it("renders and disables save when no changes", () => {
    render(<AgentSettingsComponent agentData={baseAgent} open close={() => {}} />);
    const saveBtn = screen.getByTestId("save-agent-settings");
    expect(saveBtn).toBeDisabled();
  });

  it("enables save when name changes and autoSaving true triggers saveAgent and success", async () => {
    mockAutoSaving = true;
    mockSave.mockResolvedValueOnce(undefined);
    const onClose = jest.fn();

    render(<AgentSettingsComponent agentData={baseAgent} open close={onClose} />);

    fireEvent.click(screen.getByTestId("set-name-new"));
    const saveBtn = screen.getByTestId("save-agent-settings");
    expect(saveBtn).not.toBeDisabled();

    fireEvent.click(saveBtn);

    // Wait microtask queue to resolve promise chain
    await Promise.resolve();

    expect(mockSave).toHaveBeenCalledWith(
      expect.objectContaining({ name: "New Name" }),
    );
    expect(mockSetSuccessData).toHaveBeenCalledWith({
      title: "Changes saved successfully",
    });
    expect(onClose).toHaveBeenCalled();
  });

  it("non-autoSaving path sets current agent and closes", () => {
    mockAutoSaving = false;
    const onClose = jest.fn();

    render(<AgentSettingsComponent agentData={baseAgent} open close={onClose} />);

    fireEvent.click(screen.getByTestId("set-desc-new"));
    const saveBtn = screen.getByTestId("save-agent-settings");
    expect(saveBtn).not.toBeDisabled();
    fireEvent.click(saveBtn);

    expect(mockSetCurrentAgent).toHaveBeenCalledWith(
      expect.objectContaining({ description: "New Desc" }),
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("prevents saving when name is taken", () => {
    mockAgents = [{ name: "Taken" }, { name: "agent" }];

    render(<AgentSettingsComponent agentData={baseAgent} open close={() => {}} />);

    fireEvent.click(screen.getByTestId("set-name-taken"));
    expect(screen.getByTestId("save-agent-settings")).toBeDisabled();
  });

  it("clicking cancel calls close", () => {
    const onClose = jest.fn();
    render(<AgentSettingsComponent agentData={baseAgent} open close={onClose} />);
    fireEvent.click(screen.getByTestId("cancel-agent-settings"));
    expect(onClose).toHaveBeenCalled();
  });
});
