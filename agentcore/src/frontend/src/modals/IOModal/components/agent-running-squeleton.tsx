import { TextShimmer } from "@/components/ui/TextShimmer";
import LogoIcon from "./chatView/chatMessage/components/chat-logo-icon";

export default function AgentRunningSqueleton() {
  return (
    <div className="flex gap-4 rounded-md p-2">
      <LogoIcon />
      <div className="flex items-center">
        <div>
          <TextShimmer className="" duration={1}>
            agent running...
          </TextShimmer>
        </div>
      </div>
    </div>
  );
}
