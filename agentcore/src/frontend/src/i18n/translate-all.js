import fs from "fs";
import path from "path";
import axios from "axios";
import dotenv from "dotenv";

dotenv.config();

const key = process.env.AZURE_TRANSLATOR_KEY;
const endpoint = process.env.AZURE_TRANSLATOR_ENDPOINT;
const region = process.env.AZURE_REGION;

// Load your languages list
const languages = JSON.parse(fs.readFileSync("languages.json", "utf-8"));

// Root folder where your i18n lives
const LOCALES_ROOT = path.join("i18n", "locales");

async function translateText(text, toLang) {
  const url = `${endpoint}/translate?api-version=3.0&to=${toLang}`;

  const res = await axios.post(
    url,
    [{ Text: text }],
    {
      headers: {
        "Ocp-Apim-Subscription-Key": key,
        "Ocp-Apim-Subscription-Region": region,
        "Content-Type": "application/json",
      },
    }
  );

  return res.data[0].translations[0].text;
}

async function translateAllLanguages() {
  const baseJson = JSON.parse(fs.readFileSync("en.json", "utf-8"));

  for (const lang of languages) {
    const code = lang.code;
    console.log(`Translating: ${code} (${lang.title}) ...`);

    // Create language folder if not exists
    const langFolder = path.join(LOCALES_ROOT, code);

    if (!fs.existsSync(langFolder)) {
      fs.mkdirSync(langFolder, { recursive: true });
      console.log(`📁 Created folder: ${langFolder}`);
    }

    const translatedJson = {};

    for (const key in baseJson) {
      translatedJson[key] = await translateText(baseJson[key], code);
    }

    // Save as translation.json inside the folder
    const outputPath = path.join(langFolder, "translation.json");

    fs.writeFileSync(
      outputPath,
      JSON.stringify(translatedJson, null, 2)
    );

    console.log(`✅ Saved: ${outputPath}`);
  }

  console.log("🎉 All translations completed!");
}

translateAllLanguages();
