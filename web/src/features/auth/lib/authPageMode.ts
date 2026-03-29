type AuthProviders = Record<string, unknown> & {
  credentials: boolean;
  sso: boolean;
};

export function canUsePasswordSignIn(authProviders: AuthProviders): boolean {
  return authProviders.credentials;
}

export function shouldShowSignInDiscoveryForm(
  authProviders: AuthProviders,
): boolean {
  return authProviders.credentials || authProviders.sso;
}

export function canUsePasswordSignUp(params: {
  authProviders: AuthProviders;
  signUpDisabled: boolean;
  publicSignUpDisabled: string | undefined;
}): boolean {
  return (
    params.authProviders.credentials &&
    !params.signUpDisabled &&
    params.publicSignUpDisabled !== "true"
  );
}

export function shouldShowSignUpDiscoveryForm(params: {
  authProviders: AuthProviders;
  signUpDisabled: boolean;
  publicSignUpDisabled: string | undefined;
}): boolean {
  return canUsePasswordSignUp(params) || params.authProviders.sso;
}
