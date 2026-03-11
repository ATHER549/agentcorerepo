import * as Form from "@radix-ui/react-form";
import { cloneDeep } from "lodash";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import useSaveAgent from "@/hooks/agents/use-save-agent";
import useAlertStore from "@/stores/alertStore";
import useAgentStore from "@/stores/agentStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import type { AgentType } from "@/types/agent";
import EditAgentSettings from "../editAgentSettingsComponent";

type AgentSettingsComponentProps = {
  agentData?: AgentType;
  close: () => void;
  open: boolean;
};

const updateAgentWithFormValues = (
  baseAgent: AgentType,
  newName: string,
  newDescription: string,
  newLocked: boolean,
): AgentType => {
  const newAgent = cloneDeep(baseAgent);
  newAgent.name = newName;
  newAgent.description = newDescription;
  newAgent.locked = newLocked;
  return newAgent;
};

const buildInvalidNameList = (
  allAgents: AgentType[] | undefined,
  currentAgentName: string | undefined,
): string[] => {
  if (!allAgents) return [];
  const names = allAgents.map((f) => f?.name ?? "");
  return names.filter((n) => n !== (currentAgentName ?? ""));
};

const isSaveDisabled = (
  agent: AgentType | undefined,
  invalidNameList: string[],
  name: string,
  description: string,
  locked: boolean,
): boolean => {
  if (!agent) return true;
  const isNameChangedAndValid =
    !invalidNameList.includes(name) && agent.name !== name;
  const isDescriptionChanged = agent.description !== description;
  const isLockedChanged = agent.locked !== locked;
  return !(isNameChangedAndValid || isDescriptionChanged || isLockedChanged);
};

const AgentSettingsComponent = ({
  agentData,
  close,
  open,
}: AgentSettingsComponentProps): JSX.Element => {
  const saveAgent = useSaveAgent();
  const currentAgent = useAgentStore((state) =>
    agentData ? undefined : state.currentAgent,
  );
  const setCurrentAgent = useAgentStore((state) => state.setCurrentAgent);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const agents = useAgentsManagerStore((state) => state.agents);
  const agent = agentData ?? currentAgent;
  const [name, setName] = useState(agent?.name ?? "");
  const [description, setDescription] = useState(agent?.description ?? "");
  const [locked, setLocked] = useState<boolean>(agent?.locked ?? false);
  const [isSaving, setIsSaving] = useState(false);
  const [disableSave, setDisableSave] = useState(true);
  const autoSaving = useAgentsManagerStore((state) => state.autoSaving);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    setName(agent?.name ?? "");
    setDescription(agent?.description ?? "");
    setLocked(agent?.locked ?? false);
  }, [agent?.name, agent?.description, agent?.endpoint_name, open]);

  function handleSubmit(event?: React.FormEvent<HTMLFormElement>): void {
    if (event) event.preventDefault();
    setIsSaving(true);
    if (!agent) return;
    const newAgent = updateAgentWithFormValues(agent, name, description, locked);

    if (autoSaving) {
      saveAgent(newAgent)
        ?.then(() => {
          setIsSaving(false);
          setSuccessData({ title: "Changes saved successfully" });
          close();
        })
        .catch(() => {
          setIsSaving(false);
        });
    } else {
      setCurrentAgent(newAgent);
      setIsSaving(false);
      close();
    }
  }

  const submitForm = () => {
    formRef.current?.requestSubmit();
  };

  const [nameLists, setNameList] = useState<string[]>([]);

  useEffect(() => {
    setNameList(buildInvalidNameList(agents, agent?.name));
  }, [agents]);

  useEffect(() => {
    setDisableSave(isSaveDisabled(agent, nameLists, name, description, locked));
  }, [nameLists, agent, description, name, locked]);
  return (
    <Form.Root onSubmit={handleSubmit} ref={formRef}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <EditAgentSettings
            invalidNameList={nameLists}
            name={name}
            description={description}
            setName={setName}
            setDescription={setDescription}
            submitForm={submitForm}
            locked={locked}
            setLocked={setLocked}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            data-testid="cancel-agent-settings"
            type="button"
            onClick={() => close()}
          >
            Cancel
          </Button>
          <Form.Submit asChild>
            <Button
              variant="default"
              size="sm"
              data-testid="save-agent-settings"
              loading={isSaving}
              disabled={disableSave}
            >
              Save
            </Button>
          </Form.Submit>
        </div>
      </div>
    </Form.Root>
  );
};

export default AgentSettingsComponent;
