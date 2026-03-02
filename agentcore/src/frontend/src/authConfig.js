import { LogLevel } from '@azure/msal-browser';

 export const msalConfig = {
     auth: {
         clientId: 'd717db80-a34b-43c3-b78b-41322e2058cc', // This is the ONLY mandatory field that you need to supply.
         authority: 'https://login.microsoftonline.com/69b98d34-6d85-4ddf-9d5f-6f8767b5f4b7', // Replace the placeholder with your tenant info
         redirectUri: process.env.MSAL_REDIRECT_URI || `${window.location.origin}/agents`, // Points to window.location.origin. You must register this URI on Microsoft Entra admin center/App Registration.
         postLogoutRedirectUri: '/', // Indicates the page to navigate after logout.
         navigateToLoginRequestUrl: false, // If "true", will navigate back to the original request location before processing the auth code response.
     },
     cache: {
         cacheLocation: 'sessionStorage', // Configures cache location. "sessionStorage" is more secure, but "localStorage" gives you SSO between tabs.
         storeAuthStateInCookie: false, // Set this to "true" if you are having issues on IE11 or Edge
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
     scopes: ["openid", "profile", "email"],
 };
