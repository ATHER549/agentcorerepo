import type { Users } from "../api";

export type AuthContextType = {
  accessToken: string | null;
  role: string | null;          
  permissions: string[];
  login: (
    accessToken: string,
    userRole: string,
    userPermissions: string[],
    refreshToken?: string
  ) => void;

  userData: Users | null;
  setUserData: (userData: Users | null) => void;
  authenticationErrorCount: number;
  apiKey: string | null;
  setApiKey: (apiKey: string | null) => void;
  storeApiKey: (apiKey: string) => void;
  getUser: () => void;
};
