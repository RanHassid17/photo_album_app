import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { fetchFaceClusters, fetchLabels } from "@/lib/api";

import type { FilterState } from "./types";

interface Props {
  value: FilterState;
  onChange: (next: FilterState) => void;
  onReset: () => void;
}

export function FilterPanel({ value, onChange, onReset }: Props) {
  const { t } = useTranslation();

  const clustersQ = useQuery({ queryKey: ["face-clusters"], queryFn: fetchFaceClusters });
  const labelsQ = useQuery({ queryKey: ["labels"], queryFn: fetchLabels });

  const toggleId = (key: "person_cluster_ids" | "animal_labels", id: string) => {
    const list = value[key] ?? [];
    const next = list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
    onChange({ ...value, [key]: next });
  };

  const selectedPeople = new Set(value.person_cluster_ids ?? []);
  const selectedLabels = new Set(value.animal_labels ?? []);

  return (
    <aside className="w-full md:w-72 shrink-0 rounded-lg border border-gray-200 bg-white p-4 space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t("filter.title")}</h2>
        <button
          onClick={onReset}
          className="text-xs text-gray-500 hover:text-gray-800 underline"
        >
          {t("filter.reset")}
        </button>
      </div>

      {/* People */}
      <section>
        <h3 className="text-sm font-medium text-gray-700 mb-2">{t("filter.people")}</h3>
        {clustersQ.isLoading ? (
          <p className="text-xs text-gray-400">{t("filter.loading")}</p>
        ) : clustersQ.data && clustersQ.data.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {clustersQ.data.map((c) => {
              const active = selectedPeople.has(c.id);
              return (
                <button
                  key={c.id}
                  onClick={() => toggleId("person_cluster_ids", c.id)}
                  className={`px-2.5 py-1 rounded-full border text-xs ${
                    active
                      ? "bg-indigo-600 text-white border-indigo-600"
                      : "bg-gray-50 border-gray-300 text-gray-700 hover:bg-gray-100"
                  }`}
                >
                  {c.name ?? `#${c.id.slice(0, 4)}`}
                  <span className="ms-1 opacity-70">({c.face_count})</span>
                </button>
              );
            })}
          </div>
        ) : (
          <p className="text-xs text-gray-400">{t("filter.noPeople")}</p>
        )}
      </section>

      {/* Labels */}
      <section>
        <h3 className="text-sm font-medium text-gray-700 mb-2">{t("filter.labels")}</h3>
        {labelsQ.isLoading ? (
          <p className="text-xs text-gray-400">{t("filter.loading")}</p>
        ) : labelsQ.data && labelsQ.data.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {labelsQ.data.map((l) => {
              const active = selectedLabels.has(l.label);
              return (
                <button
                  key={l.label}
                  onClick={() => toggleId("animal_labels", l.label)}
                  className={`px-2.5 py-1 rounded-full border text-xs ${
                    active
                      ? "bg-emerald-600 text-white border-emerald-600"
                      : "bg-gray-50 border-gray-300 text-gray-700 hover:bg-gray-100"
                  }`}
                >
                  {l.label}
                  <span className="ms-1 opacity-70">({l.photo_count})</span>
                </button>
              );
            })}
          </div>
        ) : (
          <p className="text-xs text-gray-400">{t("filter.noLabels")}</p>
        )}
      </section>

      {/* Date range */}
      <section className="space-y-2">
        <label className="block text-sm font-medium text-gray-700">
          {t("filter.dateFrom")}
          <input
            type="date"
            value={value.date_from?.slice(0, 10) ?? ""}
            onChange={(e) =>
              onChange({
                ...value,
                date_from: e.target.value ? `${e.target.value}T00:00:00Z` : undefined,
              })
            }
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-gray-700">
          {t("filter.dateTo")}
          <input
            type="date"
            value={value.date_to?.slice(0, 10) ?? ""}
            onChange={(e) =>
              onChange({
                ...value,
                date_to: e.target.value ? `${e.target.value}T23:59:59Z` : undefined,
              })
            }
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </label>
      </section>
    </aside>
  );
}
