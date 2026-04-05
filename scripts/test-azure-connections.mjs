/**
 * Quick smoke test for Azure Managed Redis and Azure Blob Storage
 * using DefaultAzureCredential (same auth path as the application).
 *
 * Usage:
 *   node scripts/test-azure-connections.mjs
 */

import { createRequire } from "node:module";
import * as fs from "node:fs";
import { resolve } from "node:path";

// Use createRequire to resolve packages from where pnpm installs them
const sharedRequire = createRequire(
  resolve(import.meta.dirname, "..", "packages", "shared", "node_modules", "_placeholder.js"),
);
const rootRequire = createRequire(
  resolve(import.meta.dirname, "..", "node_modules", "_placeholder.js"),
);

const { DefaultAzureCredential } = rootRequire("@azure/identity");
const { BlobServiceClient } = sharedRequire("@azure/storage-blob");
const Redis = sharedRequire("ioredis");

let dotenvParse;
try {
  dotenvParse = rootRequire("dotenv").parse;
} catch {
  dotenvParse = sharedRequire("dotenv").parse;
}

// ── Load environment ────────────────────────────────────────────────
const envPath = resolve(import.meta.dirname, "..", ".env.localdocker");
if (fs.existsSync(envPath)) {
  const fileEnv = dotenvParse(fs.readFileSync(envPath, "utf-8"));
  for (const [key, value] of Object.entries(fileEnv)) {
    if (!(key in process.env)) {
      process.env[key] = value;
    }
  }
}

const env = process.env;
const managedIdentityClientId = env.AZURE_CLIENT_ID?.trim();

const credential = new DefaultAzureCredential(
  managedIdentityClientId
    ? {
        managedIdentityClientId,
        workloadIdentityClientId: managedIdentityClientId,
      }
    : undefined,
);

// ── Test 1: Azure Blob Storage ──────────────────────────────────────
async function testBlobStorage() {
  const endpoint =
    env.LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT ||
    env.LANGFUSE_S3_BATCH_EXPORT_ENDPOINT;
  const container = env.LANGFUSE_S3_EVENT_UPLOAD_BUCKET || "langfuse";

  if (!endpoint) {
    console.error("[blob] SKIP — no blob endpoint configured");
    return false;
  }

  console.log(`[blob] Connecting to ${endpoint} ...`);
  const blobServiceClient = new BlobServiceClient(endpoint, credential);

  // 1. List containers
  console.log("[blob] Listing containers ...");
  const containers = [];
  for await (const c of blobServiceClient.listContainers()) {
    containers.push(c.name);
  }
  console.log(`[blob] Found ${containers.length} container(s): ${containers.join(", ")}`);

  // 2. Upload a test blob
  const containerClient = blobServiceClient.getContainerClient(container);
  const testBlobName = `_test/connection-test-${Date.now()}.txt`;
  const testContent = `Connection test at ${new Date().toISOString()}`;

  console.log(`[blob] Uploading test blob: ${testBlobName} ...`);
  const blockBlobClient = containerClient.getBlockBlobClient(testBlobName);
  await blockBlobClient.upload(testContent, testContent.length, {
    blobHTTPHeaders: { blobContentType: "text/plain" },
  });
  console.log("[blob] Upload OK");

  // 3. Download and verify
  console.log("[blob] Downloading test blob ...");
  const downloadResponse = await blockBlobClient.download();
  const downloaded = await streamToString(downloadResponse.readableStreamBody);
  if (downloaded === testContent) {
    console.log("[blob] Download OK — content matches");
  } else {
    console.error("[blob] FAIL — content mismatch");
    return false;
  }

  // 4. Delete test blob
  await blockBlobClient.deleteIfExists();
  console.log("[blob] Cleaned up test blob");

  // 5. Test user delegation SAS (same path as StorageService)
  console.log("[blob] Testing user delegation key ...");
  const now = new Date();
  const startsOn = new Date(now.getTime() - 5 * 60 * 1000);
  const expiresOn = new Date(now.getTime() + 3600 * 1000);
  const delegationKey = await blobServiceClient.getUserDelegationKey(
    startsOn,
    expiresOn,
  );
  console.log(
    `[blob] User delegation key OK — signed by ${delegationKey.signedObjectId}`,
  );

  console.log("[blob] All blob storage tests passed\n");
  return true;
}

// ── Test 2: Azure Managed Redis ─────────────────────────────────────
async function testRedis() {
  const useAzureAuth = env.REDIS_USE_DEFAULT_AZURE_CREDENTIAL === "true";

  const host = env.REDIS_HOST;
  const port = env.REDIS_PORT || "10000";
  const clusterNodes = env.REDIS_CLUSTER_NODES;
  const clusterEnabled = env.REDIS_CLUSTER_ENABLED === "true";
  const username = env.REDIS_USERNAME;

  if (!host && !clusterNodes) {
    console.error("[redis] SKIP — no REDIS_HOST or REDIS_CLUSTER_NODES configured");
    return false;
  }

  let password = env.REDIS_AUTH;

  if (useAzureAuth) {
    console.log("[redis] Acquiring Entra ID token for Azure Managed Redis ...");
    const tokenResponse = await credential.getToken(
      "https://redis.azure.com/.default",
    );
    if (!tokenResponse?.token) {
      console.error("[redis] FAIL — could not acquire token");
      return false;
    }
    password = tokenResponse.token;
    console.log(
      `[redis] Token acquired (expires ${new Date(tokenResponse.expiresOnTimestamp).toISOString()})`,
    );
  }

  const tlsServername = clusterEnabled
    ? clusterNodes?.split(",")[0]?.split(":")[0]
    : host;

  const tlsOptions =
    env.REDIS_TLS_ENABLED === "true"
      ? { tls: { servername: tlsServername } }
      : {};

  let client;

  if (clusterEnabled && clusterNodes) {
    const nodes = clusterNodes.split(",").map((n) => {
      const [h, p] = n.trim().split(":");
      return { host: h, port: parseInt(p, 10) };
    });

    console.log(
      `[redis] Connecting to cluster: ${nodes.map((n) => `${n.host}:${n.port}`).join(", ")} ...`,
    );

    client = new Redis.Cluster(nodes, {
      dnsLookup: (address, callback) => callback(null, address),
      slotsRefreshTimeout: parseInt(env.REDIS_CLUSTER_SLOTS_REFRESH_TIMEOUT || "10000", 10),
      redisOptions: {
        username: username || undefined,
        password: password || undefined,
        connectTimeout: 10000,
        ...tlsOptions,
      },
    });
  } else {
    console.log(`[redis] Connecting to ${host}:${port} ...`);
    client = new Redis.default({
      host,
      port: parseInt(port, 10),
      username: username || undefined,
      password: password || undefined,
      connectTimeout: 10000,
      maxRetriesPerRequest: 3,
      ...tlsOptions,
    });
  }

  try {
    await new Promise((resolve, reject) => {
      client.once("ready", resolve);
      client.once("error", reject);
      setTimeout(() => reject(new Error("Connection timeout (15s)")), 15000);
    });

    console.log("[redis] Connected");

    // SET / GET test
    const testKey = `langfuse:connection-test:${Date.now()}`;
    const testValue = `test-${Date.now()}`;

    await client.set(testKey, testValue, "EX", 30);
    const result = await client.get(testKey);
    await client.del(testKey);

    if (result === testValue) {
      console.log("[redis] SET/GET/DEL OK — round-trip verified");
    } else {
      console.error(`[redis] FAIL — expected "${testValue}", got "${result}"`);
      return false;
    }

    const pong = await client.ping();
    console.log(`[redis] PING -> ${pong}`);

    console.log("[redis] All Redis tests passed\n");
    return true;
  } finally {
    client.disconnect();
  }
}

// ── Helpers ─────────────────────────────────────────────────────────
function streamToString(readableStream) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    readableStream.on("data", (data) => chunks.push(data.toString()));
    readableStream.on("end", () => resolve(chunks.join("")));
    readableStream.on("error", reject);
  });
}

// ── Main ────────────────────────────────────────────────────────────
async function main() {
  console.log("=== Azure Connection Tests ===\n");

  let allPassed = true;

  try {
    const blobOk = await testBlobStorage();
    if (!blobOk) allPassed = false;
  } catch (err) {
    console.error("[blob] FAIL —", err.message || err);
    allPassed = false;
  }

  try {
    const redisOk = await testRedis();
    if (!redisOk) allPassed = false;
  } catch (err) {
    console.error("[redis] FAIL —", err.message || err);
    allPassed = false;
  }

  console.log(allPassed ? "=== ALL TESTS PASSED ===" : "=== SOME TESTS FAILED ===");
  process.exit(allPassed ? 0 : 1);
}

main();
