import { customGetHostProtocol } from "@/customization/utils/custom-get-host-protocol";
import type { GetCodeType } from "@/types/tweaks";

/**
 * Function to get the widget code for the API
 * @param {string} agent - The current agent.
 * @returns {string} - The widget code
 */
export default function getWidgetCode({
  agentId,
  agentName,
  isAuth,
  copy = false,
}: GetCodeType): string {
  const source = copy
    ? `<script
  src="https://cdn.jsdelivr.net/gh/logspace-ai/agentcore-embedded-chat@v1.0.7/dist/build/static/js/bundle.min.js">
</script>`
    : `<script
  src="https://cdn.jsdelivr.net/gh/logspace-ai/agentcore-embedded-chat@v1.0.7/dist/
build/static/js/bundle.min.js">
</script>`;

  const { protocol, host } = customGetHostProtocol();

  return `${source}
  <agentcore-chat
    window_title="${agentName}"
    agent_id="${agentId}"
    host_url="${protocol}//${host}"${
      !isAuth
        ? `
    api_key="..."`
        : ""
    }>
</agentcore-chat>`;
}
