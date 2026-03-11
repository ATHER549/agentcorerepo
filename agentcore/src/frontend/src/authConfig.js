import { LogLevel } from '@azure/msal-browser';

const readEnv = (key) => {
    const value = process.env[key];
    if (!value) return undefined;
    const trimmed = String(value).trim();
    if (!trimmed || trimmed.includes("${")) return undefined;
    return trimmed;
};

const clientId = readEnv("AZURE_CLIENT_ID");
const tenantId = readEnv("AZURE_TENANT_ID");
const isValidUrl = (value) => {
    if (!value) return false;
    try {
        const parsed = new URL(value);
        return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch {
        return false;
    }
};

const authorityFromEnv = readEnv("MSAL_AUTHORITY");
const authorityFromTenant = tenantId
    ? `https://login.microsoftonline.com/${tenantId}`
    : undefined;
const authority = isValidUrl(authorityFromEnv)
    ? authorityFromEnv
    : authorityFromTenant;

const redirectUriFromEnv =
    readEnv("MSAL_REDIRECT_URI") || readEnv("AZURE_REDIRECT_URI");
const redirectUriFallback = `${window.location.origin}/agents`;
const redirectUri = isValidUrl(redirectUriFromEnv)
    ? redirectUriFromEnv
    : redirectUriFallback;

const postLogoutRedirectUriFromEnv = readEnv("MSAL_POST_LOGOUT_REDIRECT_URI");
const postLogoutRedirectUri = isValidUrl(postLogoutRedirectUriFromEnv)
    ? postLogoutRedirectUriFromEnv
    : window.location.origin;
const scopes = (readEnv("MSAL_SCOPES") || "openid,profile,email")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

if (!clientId || !authority || !redirectUri) {
    // Fail fast with a clear error instead of blank MSAL popup windows.
    // Required env: AZURE_CLIENT_ID, AZURE_TENANT_ID (or MSAL_AUTHORITY), MSAL_REDIRECT_URI (or AZURE_REDIRECT_URI)
    console.error("[MSAL] Missing/invalid env configuration", {
        hasClientId: !!clientId,
        hasAuthority: !!authority,
        hasRedirectUri: !!redirectUri,
        rawAuthority: process.env.MSAL_AUTHORITY,
        rawRedirectUri: process.env.MSAL_REDIRECT_URI || process.env.AZURE_REDIRECT_URI,
    });
}

export const msalConfig = {
    auth: {
        clientId: clientId || "",
        authority,
        redirectUri: redirectUri || window.location.origin,
        postLogoutRedirectUri,
        navigateToLoginRequestUrl: false,
    },
    cache: {
        cacheLocation: "sessionStorage",
        storeAuthStateInCookie: false,
    },
    system: {
        loggerOptions: {
            loggerCallback: (level, message, containsPii) => {
                if (containsPii) {
                    return;
                }
                switch (level) {
                    case LogLevel.Error:
                        console.error(message);
                        return;
                    case LogLevel.Info:
                        console.info(message);
                        return;
                    case LogLevel.Verbose:
                        console.debug(message);
                        return;
                    case LogLevel.Warning:
                        console.warn(message);
                        return;
                    default:
                        return;
                }
            },
        },
    },
};

export const loginRequest = {
    scopes,
};
