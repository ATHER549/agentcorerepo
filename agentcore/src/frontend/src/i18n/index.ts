import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import resourcesToBackend from "i18next-resources-to-backend";
import { initReactI18next } from "react-i18next";

const localeModules = import.meta.glob("./locales/*/*.json");
export const SUPPORTED_LOCALES = Object.keys(localeModules)
  .map((path) => path.match(/\.\/locales\/([^/]+)\/translation\.json$/)?.[1])
  .filter((locale): locale is string => Boolean(locale))
  .sort((a, b) => a.localeCompare(b));

const FALLBACK_LOCALE = "en-US";

const localeMatches = (candidate: string, target: string) =>
  candidate.toLowerCase() === target.toLowerCase();

const findByLanguage = (language: string) =>
  SUPPORTED_LOCALES.find((locale) =>
    locale.toLowerCase().startsWith(`${language.toLowerCase()}-`),
  );

export const resolvePreferredLocale = (language?: string | null) => {
  const locale = language?.replace("_", "-");
  if (!locale) {
    return FALLBACK_LOCALE;
  }

  const exactMatch = SUPPORTED_LOCALES.find((candidate) =>
    localeMatches(candidate, locale),
  );
  if (exactMatch) {
    return exactMatch;
  }

  const baseLanguage = locale.split("-")[0];
  const baseMatch = findByLanguage(baseLanguage);
  if (baseMatch) {
    return baseMatch;
  }

  return FALLBACK_LOCALE;
};

const detectDefaultLocale = () => {
  const browserLocales = [
    ...(navigator.languages || []),
    navigator.language,
  ].filter(Boolean);

  for (const browserLocale of browserLocales) {
    const resolved = resolvePreferredLocale(browserLocale);
    if (resolved !== FALLBACK_LOCALE || localeMatches(browserLocale, FALLBACK_LOCALE)) {
      return resolved;
    }
  }

  return FALLBACK_LOCALE;
};

const normalizeLocale = (language?: string | null) => {
  return resolvePreferredLocale(language || detectDefaultLocale());
};

const loadResource = async (language: string, namespace: string) => {
  const normalizedLanguage = normalizeLocale(language);
  const primaryKey = `./locales/${normalizedLanguage}/${namespace}.json`;
  const fallbackKey = `./locales/${FALLBACK_LOCALE}/${namespace}.json`;

  const primaryLoader = localeModules[primaryKey];
  if (primaryLoader) {
    const module = (await primaryLoader()) as { default: Record<string, string> };
    return module.default;
  }

  const fallbackLoader = localeModules[fallbackKey];
  if (fallbackLoader) {
    const module = (await fallbackLoader()) as { default: Record<string, string> };
    return module.default;
  }

  return {};
};

i18n
  .use(resourcesToBackend(loadResource))
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    debug: false,
    fallbackLng: FALLBACK_LOCALE,
    lng: normalizeLocale(localStorage.getItem("locale") || detectDefaultLocale()),
    ns: ["translation"],
    defaultNS: "translation",
    detection: {
      order: ["querystring", "localStorage", "navigator"],
      caches: ["localStorage"],
      lookupQuerystring: "lang",
      lookupLocalStorage: "locale",
    },
    interpolation: {
      escapeValue: false,
    },
    returnEmptyString: false,
  });

(window as any).i18n = i18n;

export default i18n;
