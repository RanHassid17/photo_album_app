import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchHealth, type Health } from "@/lib/api";
import { setLanguage } from "@/lib/i18n";

type Status = "checking" | "ok" | "error";

export default function App() {
  const { t, i18n } = useTranslation();
  const [status, setStatus] = useState<Status>("checking");
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        setHealth(h);
        setStatus("ok");
      })
      .catch(() => setStatus("error"));
  }, []);

  const toggleLang = () => {
    const next = i18n.language === "he" ? "en" : "he";
    setLanguage(next);
  };

  const statusColor =
    status === "ok" ? "text-green-700" : status === "error" ? "text-red-700" : "text-gray-500";

  return (
    <main className="min-h-full flex flex-col items-center justify-center p-8 gap-6">
      <button
        onClick={toggleLang}
        className="absolute top-4 end-4 px-3 py-1 rounded border border-gray-300 hover:bg-gray-100 text-sm"
      >
        {t("lang.toggle")}
      </button>
      <h1 className="text-3xl font-bold">{t("app.title")}</h1>
      <p className="text-lg text-gray-700 max-w-md text-center">{t("app.tagline")}</p>
      <div className={`text-sm ${statusColor}`}>
        {status === "checking" && t("health.checking")}
        {status === "ok" && (
          <span>
            {t("health.ok")} <code className="ms-2 text-xs text-gray-500">v{health?.version}</code>
          </span>
        )}
        {status === "error" && t("health.error")}
      </div>
    </main>
  );
}
