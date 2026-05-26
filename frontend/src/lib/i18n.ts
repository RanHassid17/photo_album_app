import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import he from "@/i18n/he.json";
import en from "@/i18n/en.json";

export const RTL_LANGS = new Set(["he", "ar"]);

void i18n.use(initReactI18next).init({
  resources: {
    he: { translation: he },
    en: { translation: en },
  },
  lng: "he",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export function setLanguage(lng: "he" | "en"): void {
  void i18n.changeLanguage(lng);
  document.documentElement.lang = lng;
  document.documentElement.dir = RTL_LANGS.has(lng) ? "rtl" : "ltr";
}

export default i18n;
