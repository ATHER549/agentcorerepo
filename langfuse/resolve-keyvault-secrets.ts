/**
 * Azure Key Vault runtime secret injector for Langfuse.
 *
 * This script replaces `dotenv-cli` as the env loader. It:
 *   1. Loads .env file into memory (never modifies it)
 *   2. If LANGFUSE_KEY_VAULT_URL is set, fetches secrets from Azure Key Vault
 *   3. Overrides matching env vars with real secret values (in memory only)
 *   4. Spawns the actual command with the enriched environment
 *
 * Secrets exist only in process memory — nothing is written to disk.
 *
 * Usage:
 *   tsx scripts/resolve-keyvault-secrets.ts -- next dev --turbopack
 *   tsx scripts/resolve-keyvault-secrets.ts -- node dist/index.js
 */

import { existsSync, readFileSync } from "fs";
import { resolve } from "path";
import { spawn } from "child_process";
import { parse } from "dotenv";

// ---------------------------------------------------------------------------
// 1. Load .env into memory (do NOT write anywhere)
// ---------------------------------------------------------------------------
const envPath = resolve(__dirname, "..", ".env");
let fileEnv: Record<string, string> = {};
if (existsSync(envPath)) {
  fileEnv = parse(readFileSync(envPath, "utf-8"));
}

// Merge: process.env (OS-level) < .env file < (KV overrides added later)
const mergedEnv: Record<string, string> = {
  ...fileEnv,
  ...(process.env as Record<string, string>),
};

// ---------------------------------------------------------------------------
// 2. Secret mappings: env var name → Key Vault secret name
// ---------------------------------------------------------------------------
const SECRET_MAPPINGS: Record<string, string> = {
  DIRECT_URL: "langfuse-db-url",
  DATABASE_URL: "langfuse-db-url",
  CLICKHOUSE_PASSWORD: "langfuse-clickhouse-password",
  NEXTAUTH_SECRET: "langfuse-nextauthsecret",
  SALT: "langfuse-salt",
  LANGFUSE_S3_BATCH_EXPORT_SECRET_ACCESS_KEY: "langfuse-blobstorage-api-key",
  LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY: "langfuse-blobstorage-api-key",
  LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY: "langfuse-blobstorage-api-key",
  REDIS_AUTH: "agentcore-redis-password",
  ENCRYPTION_KEY: "langfuse-encryption-key",
};

// ---------------------------------------------------------------------------
// 3. Fetch secrets from Key Vault (if configured)
// ---------------------------------------------------------------------------
async function resolveKeyVaultSecrets(
  env: Record<string, string>,
): Promise<Record<string, string>> {
  const vaultUrl = (env.LANGFUSE_KEY_VAULT_URL ?? "").trim();
  if (!vaultUrl) {
    console.log(
      "[keyvault] LANGFUSE_KEY_VAULT_URL not set — skipping Key Vault.",
    );
    return env;
  }

  const { SecretClient } = await import("@azure/keyvault-secrets");
  const { ClientSecretCredential, DefaultAzureCredential } = await import(
    "@azure/identity"
  );

  const tenantId = (env.LANGFUSE_KEY_VAULT_TENANT_ID ?? "").trim() || undefined;
  const clientId = (env.LANGFUSE_KEY_VAULT_CLIENT_ID ?? "").trim() || undefined;
  const clientSecret =
    (env.LANGFUSE_KEY_VAULT_CLIENT_SECRET ?? "").trim() || undefined;

  const credential =
    tenantId && clientId && clientSecret
      ? new ClientSecretCredential(tenantId, clientId, clientSecret)
      : new DefaultAzureCredential();

  const secretClient = new SecretClient(vaultUrl, credential);
  console.log(`[keyvault] Fetching secrets from ${vaultUrl} …`);

  const resolved: string[] = [];
  const failed: string[] = [];

  for (const [envName, kvSecretName] of Object.entries(SECRET_MAPPINGS)) {
    try {
      const secret = await secretClient.getSecret(kvSecretName);
      if (!secret.value) {
        failed.push(`${envName}: secret '${kvSecretName}' is empty`);
        continue;
      }
      env[envName] = secret.value;
      resolved.push(envName);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      failed.push(`${envName} (${kvSecretName}): ${msg}`);
    }
  }

  console.log(
    `[keyvault] Injected ${resolved.length} secret(s) into runtime environment: ${resolved.join(", ")}`,
  );

  if (failed.length > 0) {
    console.error(
      `[keyvault] Failed to resolve ${failed.length} secret(s):`,
    );
    for (const f of failed) console.error(`  - ${f}`);
    process.exit(1);
  }

  return env;
}

// ---------------------------------------------------------------------------
// 4. Spawn the actual command with enriched env (secrets in memory only)
// ---------------------------------------------------------------------------
async function main() {
  const enrichedEnv = await resolveKeyVaultSecrets(mergedEnv);

  // Everything after "--" is the command to run
  const separatorIndex = process.argv.indexOf("--");
  if (separatorIndex === -1 || separatorIndex === process.argv.length - 1) {
    console.error(
      "Usage: tsx resolve-keyvault-secrets.ts -- <command> [args...]",
    );
    process.exit(1);
  }

  const [command, ...args] = process.argv.slice(separatorIndex + 1);

  const child = spawn(command, args, {
    env: enrichedEnv,
    stdio: "inherit",
  });

  // Forward signals to the child process
  for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"] as const) {
    process.on(signal, () => child.kill(signal));
  }

  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
    } else {
      process.exit(code ?? 1);
    }
  });
}

main().catch((err) => {
  console.error("[keyvault] Fatal error:", err);
  process.exit(1);
});
