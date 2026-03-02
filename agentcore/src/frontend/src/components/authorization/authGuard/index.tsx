import { useEffect } from "react";
import {
  AGENTCORE_ACCESS_TOKEN_EXPIRE_SECONDS,
  AGENTCORE_ACCESS_TOKEN_EXPIRE_SECONDS_ENV,
} from "@/constants/constants";
import { useRefreshAccessToken } from "@/controllers/API/queries/auth";
import { CustomNavigate } from "@/customization/components/custom-navigate";
import useAuthStore from "@/stores/authStore";

export const ProtectedRoute = ({ children }) => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const { mutate: mutateRefresh } = useRefreshAccessToken();

  
  const testMockAutoLogin = sessionStorage.getItem("testMockAutoLogin");

  const shouldRedirect =
    !isAuthenticated

  useEffect(() => {
    const envRefreshTime = AGENTCORE_ACCESS_TOKEN_EXPIRE_SECONDS_ENV;
    const automaticRefreshTime = AGENTCORE_ACCESS_TOKEN_EXPIRE_SECONDS;

    const accessTokenTimer = isNaN(envRefreshTime)
      ? automaticRefreshTime
      : envRefreshTime;

    const intervalFunction = () => {
      mutateRefresh();
    };

    if ( isAuthenticated) {
      const intervalId = setInterval(intervalFunction, accessTokenTimer * 1000);
      intervalFunction();
      return () => clearInterval(intervalId);
    }
  }, [isAuthenticated]);

  if (shouldRedirect || testMockAutoLogin) {
    const currentPath = window.location.pathname;
    const isHomePath = currentPath === "/" || currentPath === "/agents";
    const isLoginPage = location.pathname.includes("login");
    return (
      <CustomNavigate
        to={
          "/login" +
          (!isHomePath && !isLoginPage ? "?redirect=" + currentPath : "")
        }
        replace
      />
    );
  } else {
    return children;
  }
};
