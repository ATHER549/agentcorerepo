import { Cookies } from "react-cookie";
import { AGENTCORE_ACCESS_TOKEN } from "@/constants/constants";

export const customGetAccessToken = () => {
  const cookies = new Cookies();
  return cookies.get(AGENTCORE_ACCESS_TOKEN);
};
