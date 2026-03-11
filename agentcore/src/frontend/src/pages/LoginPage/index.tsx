import * as Form from "@radix-ui/react-form";
import { useContext, useState } from "react";
import { useLoginUser } from "@/controllers/API/queries/auth";
import { Button } from "../../components/ui/button";
import { SIGNIN_ERROR_ALERT } from "../../constants/alerts_constants";
import { CONTROL_LOGIN_STATE } from "../../constants/constants";
import { AuthContext } from "../../contexts/authContext";
import useAlertStore from "../../stores/alertStore";
import type { LoginType } from "../../types/api";
import type {
  inputHandlerEventType,
  loginInputStateType,
} from "../../types/components";

import { useMsal } from "@azure/msal-react";
import { loginRequest, msalConfig } from "@/authConfig";
import { useTranslation } from "react-i18next";
import useAuthStore from "@/stores/authStore";

import MothersonLogo from "@/assets/agentcore.svg";
import { DotPattern } from "./components/DotPattern";
import { Starfield } from "./components/StarField";

function getBackendBaseUrl(): string {
  const candidates = [
    process.env.BACKEND_URL,
    process.env.VITE_API_URL,
  ].filter(Boolean) as string[];

  const valid = candidates.find(
    (value) => !value.includes("${") && /^https?:\/\//.test(value),
  );

  return (valid || window.location.origin).replace(/\/$/, "");
}

export default function LoginPage(): JSX.Element {
  const [inputState, setInputState] =
    useState<loginInputStateType>(CONTROL_LOGIN_STATE);

  const { password, username } = inputState;

  // legacy auth context (tokens / redirect)
  const { login } = useContext(AuthContext);

  const setErrorData = useAlertStore((state) => state.setErrorData);
  const { instance } = useMsal();
  const { t } = useTranslation();

  // 🔥 ZUSTAND (REACTIVE)

  const { mutate } = useLoginUser();

  function handleInput({
    target: { name, value },
  }: inputHandlerEventType): void {
    setInputState((prev) => ({ ...prev, [name]: value }));
  }

  /* =========================
     AZURE SSO LOGIN
     ========================= */
  async function handleAzureSSO() {
    try {
      const clientId = msalConfig?.auth?.clientId;
      const authority = msalConfig?.auth?.authority;
      const redirectUri = msalConfig?.auth?.redirectUri;
      const isValidHttpUrl = (value: string | undefined) => {
        if (!value) return false;
        try {
          const parsed = new URL(value);
          return parsed.protocol === "http:" || parsed.protocol === "https:";
        } catch {
          return false;
        }
      };
      const invalidMsalConfig =
        !clientId ||
        !isValidHttpUrl(authority) ||
        !isValidHttpUrl(redirectUri);

      if (invalidMsalConfig) {
        setErrorData({
          title: "Microsoft SSO configuration is invalid",
          list: [
            "Check AZURE_CLIENT_ID, AZURE_TENANT_ID/MSAL_AUTHORITY, and MSAL_REDIRECT_URI in .env, then restart frontend.",
          ],
        });
        console.error("[SSO] Invalid MSAL config", {
          clientId,
          authority,
          redirectUri,
        });
        return;
      }

      console.log("🟣 [SSO] Starting Azure login...");

      const response = await instance.loginPopup(loginRequest);
      console.log("🟣 [SSO] Azure popup success:", response);

      const idToken = response.idToken;

      console.log("🟣 [SSO] Sending token to backend...");
      const backendBaseUrl = getBackendBaseUrl();

      const res = await fetch(
        `${backendBaseUrl}/api/azure/sso`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ idToken }),
        },
      );

      if (!res.ok) {
        let detail = "Backend SSO failed";
        try {
          const payload = await res.json();
          if (payload?.detail) detail = payload.detail;
        } catch {
          const text = await res.text();
          if (text) detail = text;
        }
        console.error("🔴 [SSO] Backend error:", detail);
        setErrorData({ title: SIGNIN_ERROR_ALERT, list: [detail] });
        return;
      }

      const data = await res.json();

      console.log("✅ [SSO] BACKEND TOKEN RESPONSE:", data);

      // legacy token handling (cookies, redirects)
      console.log("🟡 [SSO] Calling AuthContext.login()");
      login(
        data.access_token,
        data.role,
        data.permissions,
        data.refresh_token,
      );

      console.log("🟢 [SSO] Zustand AFTER SET:", useAuthStore.getState());

      // optional redirect
      // window.location.href = "/";
    } catch (err) {
      console.error("🔴 [SSO] Azure SSO failed:", err);
      setErrorData({
        title: SIGNIN_ERROR_ALERT,
        list: ["Microsoft SSO failed. Please try again or contact your admin."],
      });
    }
  }

  /* =========================
     USERNAME / PASSWORD LOGIN
     ========================= */
  function signIn() {
    const user: LoginType = {
      username: username.trim(),
      password: password.trim(),
    };

    console.log("🟣 [LOGIN] Starting username/password login...");

    mutate(user, {
      onSuccess: (data) => {
        console.log("✅ [LOGIN] BACKEND TOKEN RESPONSE:", data);

        console.log("🟡 [LOGIN] Calling AuthContext.login()");
        login(
          data.access_token,
          data.role,
          data.permissions,
          data.refresh_token,
        );

        console.log("🟢 [LOGIN] Updating Zustand auth store...");
        setAuthContext({
          role: data.role,
          permissions: data.permissions,
        });
        setIsAuthenticated(true);

        console.log("🟢 [LOGIN] Zustand AFTER SET:", useAuthStore.getState());
      },
      onError: (error) => {
        console.error("🔴 [LOGIN] Login failed:", error);
        setErrorData({
          title: SIGNIN_ERROR_ALERT,
          list: [error["response"]["data"]["detail"]],
        });
      },
    });
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-100 text-gray-900 overflow-hidden relative">
      {/* Background decorative elements */}
      <div className="absolute inset-0 opacity-30">
        <div className="absolute top-0 right-0 w-64 h-64 sm:w-96 sm:h-96 bg-purple-200 rounded-full filter blur-3xl"></div>
        <div className="absolute bottom-0 left-0 w-64 h-64 sm:w-96 sm:h-96 bg-blue-200 rounded-full filter blur-3xl"></div>
      </div>
      
      {/* Dot pattern with dark dots for white background */}
      <div className="absolute inset-0 opacity-[0.25]">
        <div className="absolute inset-0" style={{
          backgroundImage: 'radial-gradient(circle, #6b7280 1px, transparent 1px)',
          backgroundSize: '24px 24px'
        }}></div>
      </div>

      <div className="relative z-10 min-h-screen flex flex-col lg:flex-row">
        {/* LEFT SIDE */}
        <div className="flex-1 flex flex-col justify-center px-4 sm:px-6 md:px-12 lg:px-16 xl:px-24 py-8 sm:py-12 lg:py-0">
          <div className="mb-6 sm:mb-8">
            <img 
              src={MothersonLogo} 
              alt={t("AgentCore Logo")} 
              className="h-12 sm:h-16 md:h-20 w-auto"
            />
          </div>

          <div className="max-w-md">
            <h1 className="text-2xl sm:text-3xl md:text-4xl lg:text-5xl mb-3 sm:mb-4 font-bold text-gray-900 leading-tight">
              {t("Build AI Agents, faster.")}
            </h1>
            <p className="text-sm sm:text-base lg:text-lg text-gray-600 mb-6 sm:mb-8">
              {t(
                "Connect your ideas to reality with AgentCore's powerful platform.",
              )}
            </p>
          </div>
        </div>

        {/* SEPARATOR LINE - Vertical on desktop, Horizontal on mobile */}
        <div className="relative">
          {/* Desktop separator (vertical) - thicker with padding */}
          <div className="hidden lg:block absolute top-16 bottom-16 left-0 w-[2px] bg-gradient-to-b from-transparent via-[#da2128] to-transparent opacity-40"></div>
          
          {/* Mobile separator (horizontal) - thicker with padding */}
          <div className="lg:hidden mx-8 sm:mx-12 h-[2px] bg-gradient-to-r from-transparent via-[#da2128] to-transparent opacity-40 my-8"></div>
        </div>

        {/* RIGHT SIDE */}
        <div className="flex-1 flex items-center justify-center px-4 sm:px-6 md:px-12 lg:px-16 py-8 sm:py-12 lg:py-0">
          <div className="w-full max-w-md">
            {/* Login Card */}
            <div className="bg-white rounded-xl sm:rounded-2xl shadow-xl border border-gray-200 p-6 sm:p-8 md:p-10">
              <div className="mb-6 sm:mb-8 text-center">
                <h2 className="text-xl sm:text-2xl md:text-3xl mb-2 font-semibold text-gray-900">
                  {t("Welcome back.")}
                </h2>

                <p className="text-gray-600 text-xs sm:text-sm md:text-base px-2">
                  {t("Sign in to your account to continue building intelligent agents.")}
                </p>
              </div>

              <Form.Root
                onSubmit={(event) => {
                  event.preventDefault();
                  if (password !== "") signIn();
                }}
                className="space-y-4"
              >
                <div className="grid grid-cols-1 gap-3">
                  <Button
                    type="button"
                    onClick={handleAzureSSO}
                    className="h-11 sm:h-12 !bg-[var(--button-primary)] hover:!bg-[var(--button-primary-hover)] disabled:!bg-[var(--button-primary-disabled)] text-white flex items-center justify-center gap-2 rounded-lg font-medium transition-all text-sm sm:text-base"
                  >
                    <svg className="w-4 h-4 sm:w-5 sm:h-5" viewBox="0 0 23 23">
                      <path fill="#f25022" d="M1 1h10v10H1z" />
                      <path fill="#7fba00" d="M12 1h10v10H12z" />
                      <path fill="#00a4ef" d="M1 12h10v10H1z" />
                      <path fill="#ffb900" d="M12 12h10v10H12z" />
                    </svg>
                    <span className="whitespace-nowrap">{t("Continue with Microsoft SSO")}</span>
                  </Button>
                </div>
              </Form.Root>
              
              <div className="mt-4 sm:mt-6 text-center">
                <p className="text-[10px] sm:text-xs text-gray-500 px-2">
                  {t("By signing in, you agree to our Terms of Service and Privacy Policy")}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
