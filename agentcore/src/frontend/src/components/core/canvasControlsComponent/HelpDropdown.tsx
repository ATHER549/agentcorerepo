import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { HelpDropdownView } from "@/components/core/canvasControlsComponent/HelpDropdownView";
import { ENABLE_AGENTCORE } from "@/customization/feature-flags";
import useAgentStore from "@/stores/agentStore";

const HelpDropdown = () => {
  const navigate = useNavigate();
  const [isHelpMenuOpen, setIsHelpMenuOpen] = useState(false);

  const helperLineEnabled = useAgentStore((state) => state.helperLineEnabled);
  const setHelperLineEnabled = useAgentStore(
    (state) => state.setHelperLineEnabled,
  );

  const onToggleHelperLines = useCallback(() => {
    setHelperLineEnabled(!helperLineEnabled);
  }, [helperLineEnabled, setHelperLineEnabled]);

  return (
    <HelpDropdownView
      isOpen={isHelpMenuOpen}
      onOpenChange={setIsHelpMenuOpen}
      helperLineEnabled={helperLineEnabled}
      onToggleHelperLines={onToggleHelperLines}
      navigateTo={(path) => navigate(path)}
      openLink={(url) => window.open(url, "_blank")}
      urls={{
        docs: "",
        bugReport: "",
        desktop: "",
      }}
    />
  );
};

export default HelpDropdown;