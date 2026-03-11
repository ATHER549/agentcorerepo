import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { v4 as uuid } from "uuid";
import { useTranslation } from "react-i18next";
import { useGetConfig } from "@/controllers/API/queries/config/use-get-config";
import { useGetAgent } from "@/controllers/API/queries/agents/use-get-agent";
import { CustomIOModal } from "@/customization/components/custom-new-modal";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { track } from "@/customization/utils/analytics";
import useAgentStore from "@/stores/agentStore";
import { useUtilityStore } from "@/stores/utilityStore";
import { type CookieOptions, getCookie, setCookie } from "@/utils/utils";
import useAgentsManagerStore from "../../stores/agentsManagerStore";
import { getInputsAndOutputs } from "../../utils/storeUtils";
export default function PlaygroundPage() {
  const { t } = useTranslation();
  useGetConfig();
  const setCurrentAgent = useAgentsManagerStore((state) => state.setCurrentAgent);
  const currentSavedAgent = useAgentsManagerStore((state) => state.currentAgent);
  const setClientId = useUtilityStore((state) => state.setClientId);

  const { id } = useParams();
  const { mutateAsync: getAgent } = useGetAgent();

  const navigate = useCustomNavigate();

  const currentAgentId = useAgentsManagerStore((state) => state.currentAgentId);
  const setIsLoading = useAgentsManagerStore((state) => state.setIsLoading);
  const setPlaygroundPage = useAgentStore((state) => state.setPlaygroundPage);

  async function getAgentData() {
    try {
      const agent = await getAgent({ id: id!, public: true });
      return agent;
    } catch (error: any) {
      console.error(error);
      navigate("/");
    }
  }

  useEffect(() => {
    const initializeAgent = async () => {
      setIsLoading(true);
      if (currentAgentId === "") {
        const agent = await getAgentData();
        if (agent) {
          setCurrentAgent(agent);
        } else {
          navigate("/");
        }
      }
    };

    initializeAgent();
    setIsLoading(false);
  }, [id]);

  useEffect(() => {
    if (id) track("Playground Page Loaded", { agentId: id });
    setPlaygroundPage(true);
  }, []);

  useEffect(() => {
    document.title = currentSavedAgent?.name || t("AgentCore");
    if (currentSavedAgent?.data) {
      const { inputs, outputs } = getInputsAndOutputs(
        currentSavedAgent?.data?.nodes || [],
      );
      if (
        (inputs.length === 0 && outputs.length === 0) ||
        currentSavedAgent?.access_type !== "PUBLIC"
      ) {
        // redirect to the home page
        navigate("/");
      }
    }
  }, [currentSavedAgent, t]);

  useEffect(() => {
    // Get client ID from cookie or create new one
    const clientId = getCookie("client_id");
    if (!clientId) {
      const newClientId = uuid();
      const cookieOptions: CookieOptions = {
        secure: window.location.protocol === "https:",
        sameSite: "Strict",
      };
      setCookie("client_id", newClientId, cookieOptions);
      setClientId(newClientId);
    } else {
      setClientId(clientId);
    }
  }, []);

  return (
    <div className="flex h-full w-full flex-col items-center justify-center align-middle">
      {currentSavedAgent && (
        <CustomIOModal
          open={true}
          setOpen={() => {}}
          isPlayground
          playgroundPage
        >
          <></>
        </CustomIOModal>
      )}
    </div>
  );
}
