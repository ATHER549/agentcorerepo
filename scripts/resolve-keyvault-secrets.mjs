/**
 * Azure Key Vault runtime secret injector for Langfuse.
 *
 * Modes:
 *   1. spawn mode (default): node resolve-keyvault-secrets.mjs -- <command> [args...]
 *   2. shell export mode:      node resolve-keyvault-secrets.mjs --export-shell
 */

import { spawn } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'dotenv';

const envPath = resolve(import.meta.dirname, '..', '.env');
let fileEnv = {};
if (existsSync(envPath)) {
  fileEnv = parse(readFileSync(envPath, 'utf-8'));
}

const baseEnv = process.env;
const mergedEnv = {
  ...fileEnv,
  ...baseEnv,
};

/** Required secrets – the process exits if any of these cannot be resolved. */
const SECRET_MAPPINGS = {
  DIRECT_URL: 'langfuse-db-url',
  DATABASE_URL: 'langfuse-db-url',
  CLICKHOUSE_PASSWORD: 'langfuse-clickhouse-password',
  NEXTAUTH_SECRET: 'langfuse-nextauthsecret',
  SALT: 'langfuse-salt',
  ENCRYPTION_KEY: 'langfuse-encryption-key',
};

/**
 * Optional secrets – resolved when present in Key Vault, silently skipped otherwise.
 * Blob storage keys are optional because DefaultAzureCredential is the primary auth
 * method; keys are only needed for backward-compatible / hybrid deployments.
 * REDIS_AUTH is optional because Azure Managed Redis uses token-based auth
 * (injected by resolveAzureManagedRedisToken) when REDIS_USE_DEFAULT_AZURE_CREDENTIAL=true.
 */
const OPTIONAL_SECRET_MAPPINGS = {
  LANGFUSE_S3_BATCH_EXPORT_SECRET_ACCESS_KEY: 'langfuse-blobstorage-api-key',
  LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY: 'langfuse-blobstorage-api-key',
  LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY: 'langfuse-blobstorage-api-key',
  REDIS_AUTH: 'agentcore-redis-password-local',
};

const AZURE_MANAGED_REDIS_SCOPE = 'https://redis.azure.com/.default';

const syncAzureIdentityEnv = (env) => {
  for (const key of [
    'AZURE_CLIENT_ID',
    'AZURE_TENANT_ID',
    'AZURE_CLIENT_SECRET',
    'AZURE_TOKEN_CREDENTIALS',
  ]) {
    const value = env[key];
    if (typeof value === 'string' && value.trim()) {
      process.env[key] = value;
    }
  }
};

const createDefaultAzureCredential = async (env) => {
  const { DefaultAzureCredential } = await import('@azure/identity');
  const managedIdentityClientId = env.AZURE_CLIENT_ID?.trim();

  return new DefaultAzureCredential(
    managedIdentityClientId
      ? {
          managedIdentityClientId,
          workloadIdentityClientId: managedIdentityClientId,
        }
      : undefined,
  );
};

async function resolveKeyVaultSecrets(env) {
  const vaultUrl = (env.LANGFUSE_KEY_VAULT_URL ?? '').trim();
  if (!vaultUrl) {
    return env;
  }

  syncAzureIdentityEnv(env);

  const { SecretClient } = await import('@azure/keyvault-secrets');
  const credential = await createDefaultAzureCredential(env);

  const secretClient = new SecretClient(vaultUrl, credential);
  console.error(`[keyvault] Fetching secrets from ${vaultUrl} ...`);

  const resolved = [];
  const failed = [];

  // Resolve required secrets – failure is fatal.
  for (const [envName, kvSecretName] of Object.entries(SECRET_MAPPINGS)) {
    try {
      const secret = await secretClient.getSecret(kvSecretName);
      if (!secret.value) {
        failed.push(`${envName}: secret '${kvSecretName}' is empty`);
        continue;
      }
      env[envName] = secret.value;
      resolved.push(envName);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      failed.push(`${envName} (${kvSecretName}): ${message}`);
    }
  }

  if (failed.length > 0) {
    console.error(`[keyvault] Failed to resolve ${failed.length} required secret(s):`);
    for (const failure of failed) {
      console.error(`  - ${failure}`);
    }
    process.exit(1);
  }

  // Resolve optional secrets – missing secrets are silently skipped.
  const skipped = [];
  for (const [envName, kvSecretName] of Object.entries(OPTIONAL_SECRET_MAPPINGS)) {
    if (
      env.REDIS_USE_DEFAULT_AZURE_CREDENTIAL === 'true' &&
      envName === 'REDIS_AUTH'
    ) {
      continue;
    }

    try {
      const secret = await secretClient.getSecret(kvSecretName);
      if (secret.value) {
        env[envName] = secret.value;
        resolved.push(envName);
      } else {
        skipped.push(envName);
      }
    } catch {
      skipped.push(envName);
    }
  }

  console.error(
    `[keyvault] Injected ${resolved.length} secret(s) into runtime environment: ${resolved.join(', ')}`,
  );

  if (skipped.length > 0) {
    console.error(
      `[keyvault] Skipped ${skipped.length} optional secret(s) (not found or empty): ${skipped.join(', ')}`,
    );
  }

  return env;
}

async function resolveAzureManagedRedisToken(env) {
  if ((env.REDIS_USE_DEFAULT_AZURE_CREDENTIAL ?? '').trim() !== 'true') {
    return env;
  }

  if (!(env.REDIS_USERNAME ?? '').trim()) {
    console.error(
      '[redis] REDIS_USERNAME must be set to the Microsoft Entra object ID when REDIS_USE_DEFAULT_AZURE_CREDENTIAL=true',
    );
    process.exit(1);
  }

  syncAzureIdentityEnv(env);

  const credential = await createDefaultAzureCredential(env);
  const accessToken = await credential.getToken(AZURE_MANAGED_REDIS_SCOPE);

  if (!accessToken?.token) {
    console.error(
      '[redis] DefaultAzureCredential did not return an Azure Managed Redis access token',
    );
    process.exit(1);
  }

  env.REDIS_AUTH = accessToken.token;
  console.error('[redis] Injected Azure Managed Redis access token into runtime environment');

  return env;
}

function shellEscape(value) {
  return `'${String(value).replace(/'/g, `"'"'`)}'`;
}

function exportShell(env) {
  const exportKeys = new Set([
    ...Object.keys(fileEnv),
    ...Object.keys(SECRET_MAPPINGS),
    ...Object.keys(OPTIONAL_SECRET_MAPPINGS),
    'LANGFUSE_KEY_VAULT_URL',
  ]);

  const lines = [];
  for (const key of exportKeys) {
    const value = env[key];
    if (typeof value === 'string') {
      lines.push(`export ${key}=${shellEscape(value)}`);
    }
  }
  return `${lines.join('\n')}\n`;
}

async function main() {
  const exportMode = process.argv.includes('--export-shell');
  const withKeyVaultEnv = await resolveKeyVaultSecrets({ ...mergedEnv });
  const enrichedEnv = await resolveAzureManagedRedisToken(withKeyVaultEnv);

  if (exportMode) {
    process.stdout.write(exportShell(enrichedEnv));
    return;
  }

  const separatorIndex = process.argv.indexOf('--');
  if (separatorIndex === -1 || separatorIndex === process.argv.length - 1) {
    console.error('Usage: node resolve-keyvault-secrets.mjs -- <command> [args...]');
    process.exit(1);
  }

  const [command, ...args] = process.argv.slice(separatorIndex + 1);
  const child = spawn(command, args, {
    env: enrichedEnv,
    stdio: 'inherit',
  });

  for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(signal, () => child.kill(signal));
  }

  child.on('exit', (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
    } else {
      process.exit(code ?? 1);
    }
  });
}

main().catch((error) => {
  console.error('[keyvault] Fatal error:', error);
  process.exit(1);
});
