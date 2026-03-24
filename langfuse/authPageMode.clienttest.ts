import {
  canUsePasswordSignIn,
  canUsePasswordSignUp,
  shouldShowSignInDiscoveryForm,
  shouldShowSignUpDiscoveryForm,
} from "@/src/features/auth/lib/authPageMode";

const baseAuthProviders = {
  credentials: true,
  google: false,
  github: false,
  githubEnterprise: false,
  gitlab: false,
  okta: false,
  authentik: false,
  onelogin: false,
  azureAd: false,
  auth0: false,
  clickhouseCloud: false,
  cognito: false,
  keycloak: false,
  workos: false,
  wordpress: false,
  custom: false,
  sso: false,
};

describe("authPageMode", () => {
  it("keeps password sign-in enabled when credentials auth is enabled", () => {
    expect(canUsePasswordSignIn(baseAuthProviders)).toBe(true);
    expect(shouldShowSignInDiscoveryForm(baseAuthProviders)).toBe(true);
  });

  it("still shows sign-in discovery when only tenant SSO is enabled", () => {
    const authProviders = {
      ...baseAuthProviders,
      credentials: false,
      sso: true,
    };

    expect(canUsePasswordSignIn(authProviders)).toBe(false);
    expect(shouldShowSignInDiscoveryForm(authProviders)).toBe(true);
  });

  it("disables password signup when credentials auth is disabled", () => {
    const authProviders = {
      ...baseAuthProviders,
      credentials: false,
      azureAd: true,
    };

    expect(
      canUsePasswordSignUp({
        authProviders,
        signUpDisabled: false,
        publicSignUpDisabled: undefined,
      }),
    ).toBe(false);
    expect(
      shouldShowSignUpDiscoveryForm({
        authProviders,
        signUpDisabled: false,
        publicSignUpDisabled: undefined,
      }),
    ).toBe(false);
  });

  it("keeps signup discovery available for tenant SSO without passwords", () => {
    const authProviders = {
      ...baseAuthProviders,
      credentials: false,
      sso: true,
    };

    expect(
      shouldShowSignUpDiscoveryForm({
        authProviders,
        signUpDisabled: false,
        publicSignUpDisabled: undefined,
      }),
    ).toBe(true);
  });

  it("disables password signup when signup is globally disabled", () => {
    expect(
      canUsePasswordSignUp({
        authProviders: baseAuthProviders,
        signUpDisabled: true,
        publicSignUpDisabled: undefined,
      }),
    ).toBe(false);
    expect(
      canUsePasswordSignUp({
        authProviders: baseAuthProviders,
        signUpDisabled: false,
        publicSignUpDisabled: "true",
      }),
    ).toBe(false);
  });
});
