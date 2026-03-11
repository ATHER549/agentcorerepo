import { FaDiscord, FaGithub } from "react-icons/fa";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { DISCORD_URL } from "@/constants/constants";
import { useDarkStore } from "@/stores/darkStore";
import { formatNumber } from "@/utils/utils";

export const AgentCoreCounts = () => {
  const stars: number | undefined = useDarkStore((state) => state.stars);
  const discordCount: number = useDarkStore((state) => state.discordCount);

  return (
    <div
      className="flex items-center gap-3"
      
    >
      
    </div>
  );
};

export default AgentCoreCounts;
