import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { FilterPanel } from "@/features/filter/FilterPanel";
import { PhotoGrid } from "@/features/filter/PhotoGrid";
import { emptyFilter, type FilterState } from "@/features/filter/types";
import { fetchHealth, type Health } from "@/lib/api";
import { setLanguage } from "@/lib/i18n";

type Status = "checking" | "ok" | "error";

export default function App() {
  const { t, i18n } = useTranslation();
  const [status, setStatus] = useState<Status>("checking");
  const [health, setHealth] = useState<Health | null>(null);
  const [filter, setFilter] = useState<FilterState>(emptyFilter);

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
    <main className="min-h-full p-6 md:p-8">
      <header className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold">{t("app.title")}</h1>
          <p className="text-sm text-gray-600 mt-1 max-w-xl">{t("app.tagline")}</p>
          <div className={`mt-2 text-xs ${statusColor}`}>
            {status === "checking" && t("health.checking")}
            {status === "ok" && (
              <span>
                {t("health.ok")}{" "}
                <code className="ms-2 text-[10px] text-gray-500">v{health?.version}</code>
              </span>
            )}
            {status === "error" && t("health.error")}
          </div>
        </div>
        <button
          onClick={toggleLang}
          className="px-3 py-1 rounded border border-gray-300 hover:bg-gray-100 text-sm"
        >
          {t("lang.toggle")}
        </button>
      </header>

      <div className="flex flex-col md:flex-row gap-6">
        <FilterPanel
          value={filter}
          onChange={setFilter}
          onReset={() => setFilter(emptyFilter)}
        />
        <PhotoGrid filter={filter} />
      </div>
    </main>
  );
}
