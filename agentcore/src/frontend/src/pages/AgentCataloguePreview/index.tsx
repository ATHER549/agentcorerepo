import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useGetTypes } from "@/controllers/API/queries/agents/use-get-types";
import { useGetRegistryPreview } from "@/controllers/API/queries/registry";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import CustomLoader from "@/customization/components/custom-loader";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { useTypesStore } from "@/stores/typesStore";
import Page from "../AgentBuilderPage/components/PageComponent";

export default function AgentCataloguePreviewPage(): JSX.Element {
  const { t } = useTranslation();
  const navigate = useCustomNavigate();
  const { registryId } = useParams();
  const types = useTypesStore((state) => state.types);
  const setCurrentAgent = useAgentsManagerStore((state) => state.setCurrentAgent);

  useGetTypes({
    enabled: Object.keys(types).length <= 0,
  });

  const { data: previewAgent, isLoading, isFetching } = useGetRegistryPreview(
    { registry_id: registryId || "" },
    { enabled: !!registryId },
  );

  useEffect(() => {
    if (previewAgent) {
      setCurrentAgent(previewAgent);
    }

    return () => {
      setCurrentAgent(undefined);
    };
  }, [previewAgent, setCurrentAgent]);

  const subtitle = useMemo(() => {
    if (!previewAgent?.data?.nodes?.length) {
      return t("No components available in this deployed snapshot.");
    }
    return t("{{count}} component(s)", { count: previewAgent.data.nodes.length });
  }, [previewAgent, t]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">{previewAgent?.name || t("Agent Preview")}</h1>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <Button variant="outline" onClick={() => navigate("/agent-catalogue")}>
          {t("Back to Registry")}
        </Button>
      </div>
      <div className="h-full w-full">
        {isLoading || isFetching || !previewAgent ? (
          <div className="flex h-full w-full items-center justify-center">
            <CustomLoader />
          </div>
        ) : (
          <Page
            view
            enableViewportInteractions
            setIsLoading={() => undefined}
          />
        )}
      </div>
    </div>
  );
}
