export const track = async (
  name: string,
  properties: Record<string, any> = {},
  id: string = "",
): Promise<void> => {
  return;
};

export const trackAgentBuild = async (
  agentName: string,
  isError?: boolean,
  properties?: Record<string, any>,
): Promise<void> => {
  return;
};

export const trackDataLoaded = async (
  agentId?: string,
  agentName?: string,
  component?: string,
  componentId?: string,
): Promise<void> => {
  return;
};
