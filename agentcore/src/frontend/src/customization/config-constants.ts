export const BASENAME = "";
export const PORT = 3000;
export const PROXY_TARGET =
  process.env.VITE_PROXY_TARGET ||
  process.env.BACKEND_URL ||
  `http://${process.env.HOST_IP || "127.0.0.1"}:${process.env.BACKEND_PORT || "7860"}`;
export const API_ROUTES = ["^/api/", "^/api/", "/health"];
export const BASE_URL_API = "/api/";
export const BASE_URL_API_V2 = "/api/";
export const HEALTH_CHECK_URL = "/health_check";
export const DOCS_LINK = "https://www.motherson.com/";

export default {
  DOCS_LINK,
  BASENAME,
  PORT,
  PROXY_TARGET,
  API_ROUTES,
  BASE_URL_API,
  BASE_URL_API_V2,
  HEALTH_CHECK_URL,
};
