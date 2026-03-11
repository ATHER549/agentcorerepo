import React from "react";
import ReactDOM from "react-dom/client";
import reportWebVitals from "./reportWebVitals";
import { I18nextProvider } from "react-i18next";
import i18n from "./i18n";

import "./style/classes.css";
// @ts-ignore
import "./style/index.css";
// @ts-ignore
import "./App.css";
import "./style/applies.css";

// @ts-ignore
import App from "./customization/custom-App";



/* ================= MSAL IMPORTS ================= */
import { PublicClientApplication, EventType, AuthenticationResult  } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { msalConfig } from "./authConfig";

/* ================================================ */

/**
 * MSAL instance should be created outside React tree
 */
const msalInstance = new PublicClientApplication(msalConfig);

// If user already logged in, set active account
const accounts = msalInstance.getAllAccounts();
if (!msalInstance.getActiveAccount() && accounts.length > 0) {
  msalInstance.setActiveAccount(accounts[0]);
}

// Listen for login success and set account
msalInstance.addEventCallback((event) => {
  if (event.eventType === EventType.LOGIN_SUCCESS && event.payload) {
    const payload = event.payload as AuthenticationResult;
    if (payload.account) {
      msalInstance.setActiveAccount(payload.account);
    }
  }
});

/* ============== REACT ROOT ================= */

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement
);

// If your App DOES NOT need msalInstance yet → just keep <App />
// If you want SSO inside app → pass instance as prop

root.render(
  <React.StrictMode>
    <I18nextProvider i18n={i18n}>
      <MsalProvider instance={msalInstance}>
        <App />
      </MsalProvider>
    </I18nextProvider>
  </React.StrictMode>
);

reportWebVitals();
