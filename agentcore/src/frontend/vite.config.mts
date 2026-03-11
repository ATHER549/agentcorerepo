import react from "@vitejs/plugin-react-swc";
import * as dotenv from "dotenv";
import path from "path";
import { defineConfig, loadEnv } from "vite";
import svgr from "vite-plugin-svgr";
import tsconfigPaths from "vite-tsconfig-paths";
import {
  API_ROUTES,
  BASENAME,
  PORT,
  PROXY_TARGET,
} from "./src/customization/config-constants";

function expandEnvVars(envMap: Record<string, string>): Record<string, string> {
  const expanded: Record<string, string> = { ...envMap };

  const resolveValue = (value: string, depth = 0): string => {
    if (depth > 10 || !value.includes("${")) return value;
    return value.replace(/\$\{([^}]+)\}/g, (_match, key: string) => {
      const replacement = expanded[key] ?? process.env[key] ?? "";
      return resolveValue(replacement, depth + 1);
    });
  };

  for (const [key, value] of Object.entries(expanded)) {
    expanded[key] = resolveValue(value);
  }

  return expanded;
}

function ensureHttpUrl(candidate: string | undefined, fallback: string): string {
  if (!candidate) return fallback;
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.toString().replace(/\/$/, "");
    }
  } catch {
    // Fallback below
  }
  return fallback;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  const envAgentCoreResult = dotenv.config({
    path: path.resolve(__dirname, "../../.env"),
  });

  const envAgentCore = expandEnvVars(envAgentCoreResult.parsed || {});
  const hostIp =
    envAgentCore.HOST_IP ||
    env.HOST_IP ||
    "127.0.0.1";
  const backendPort = envAgentCore.BACKEND_PORT || env.BACKEND_PORT || "7860";
  const frontendPort = envAgentCore.FRONTEND_PORT || env.FRONTEND_PORT || "3000";
  const publishPort =
    envAgentCore.AGENTCORE_PUBLISH_PORT ||
    env.AGENTCORE_PUBLISH_PORT ||
    "5839";
  const backendUrlDefault = ensureHttpUrl(`http://${hostIp}:${backendPort}`, "http://127.0.0.1:7860");
  const msalRedirectUriDefault = ensureHttpUrl(`http://${hostIp}:${frontendPort}/agents`, "http://127.0.0.1:3000/agents");
  const msalPostLogoutRedirectUriDefault = ensureHttpUrl(`http://${hostIp}:${frontendPort}`, "http://127.0.0.1:3000");
  const msalAuthorityDefault =
    envAgentCore.AZURE_TENANT_ID
      ? `https://login.microsoftonline.com/${envAgentCore.AZURE_TENANT_ID}`
      : undefined;
  const agentcorePublishUrlDefault = ensureHttpUrl(`http://${hostIp}:${publishPort}`, "http://127.0.0.1:5839");

  const apiRoutes = API_ROUTES || ["^/api/", "^/api/", "/health"];

  const target = ensureHttpUrl(
    envAgentCore.VITE_PROXY_TARGET ||
    env.VITE_PROXY_TARGET ||
    PROXY_TARGET ||
    envAgentCore.BACKEND_URL ||
    backendUrlDefault,
    backendUrlDefault,
  );

  const port = Number(envAgentCore.VITE_PORT || env.VITE_PORT) || PORT || 3000;

  const proxyTargets = apiRoutes.reduce((proxyObj: Record<string, any>, route) => {
    proxyObj[route] = {
      target: target,
      changeOrigin: true,
      secure: false,
      ws: true,
      // Ensure streaming (SSE / NDJSON) responses are forwarded
      // chunk-by-chunk without buffering by the dev-server proxy.
      configure: (proxy: any) => {
        proxy.on("proxyRes", (proxyRes: any, _req: any, res: any) => {
          const ct = proxyRes.headers["content-type"] || "";
          if (ct.includes("text/event-stream") || ct.includes("application/x-ndjson")) {
            // Prevent Node / proxy from coalescing small chunks
            res.setHeader("X-Accel-Buffering", "no");
            res.setHeader("Cache-Control", "no-cache, no-transform");
            if (typeof res.flushHeaders === "function") {
              res.flushHeaders();
            }
          }
        });
      },
    };
    return proxyObj;
  }, {});

  return {
    base: BASENAME || "",
    build: {
      outDir: "build",
    },
    define: {
      "process.env.BACKEND_URL": JSON.stringify(
        envAgentCore.BACKEND_URL ?? backendUrlDefault,
      ),
      "process.env.ACCESS_TOKEN_EXPIRE_SECONDS": JSON.stringify(
        envAgentCore.ACCESS_TOKEN_EXPIRE_SECONDS ?? 60,
      ),
      "process.env.CI": JSON.stringify(envAgentCore.CI ?? false),
      "process.env.AGENTCORE_MCP_COMPOSER_ENABLED": JSON.stringify(
        envAgentCore.AGENTCORE_MCP_COMPOSER_ENABLED ?? "true",
      ),
      "process.env.MSAL_REDIRECT_URI": JSON.stringify(
        envAgentCore.MSAL_REDIRECT_URI ?? msalRedirectUriDefault,
      ),
      "process.env.MSAL_POST_LOGOUT_REDIRECT_URI": JSON.stringify(
        envAgentCore.MSAL_POST_LOGOUT_REDIRECT_URI ?? msalPostLogoutRedirectUriDefault,
      ),
      "process.env.AZURE_CLIENT_ID": JSON.stringify(
        envAgentCore.AZURE_CLIENT_ID ?? "",
      ),
      "process.env.AZURE_TENANT_ID": JSON.stringify(
        envAgentCore.AZURE_TENANT_ID ?? "",
      ),
      "process.env.AZURE_REDIRECT_URI": JSON.stringify(
        envAgentCore.AZURE_REDIRECT_URI ?? msalRedirectUriDefault,
      ),
      "process.env.MSAL_AUTHORITY": JSON.stringify(
        envAgentCore.MSAL_AUTHORITY ?? msalAuthorityDefault ?? "",
      ),
      "process.env.MSAL_SCOPES": JSON.stringify(
        envAgentCore.MSAL_SCOPES ?? "openid,profile,email",
      ),
      "process.env.AGENTCORE_PUBLISH_URL": JSON.stringify(
        envAgentCore.AGENTCORE_PUBLISH_URL ?? agentcorePublishUrlDefault,
      ),
      "process.env.DEFAULT_CONNECTOR_HOST": JSON.stringify(
        envAgentCore.DEFAULT_CONNECTOR_HOST ?? hostIp,
      ),
      "process.env.LOCALHOST_HOST": JSON.stringify(
        envAgentCore.HOST_IP ?? hostIp,
      ),
      "process.env.HOST_IP": JSON.stringify(hostIp),
      "process.env.BACKEND_PORT": JSON.stringify(backendPort),
      "process.env.FRONTEND_PORT": JSON.stringify(frontendPort),
    },
    plugins: [react(), svgr(), tsconfigPaths()],
    server: {
      port: port,
      proxy: {
        ...proxyTargets,
      },
    },
  };
});
