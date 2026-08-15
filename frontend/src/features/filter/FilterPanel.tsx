import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  faceClusterThumbUrl,
  fetchFaceClusters,
  fetchLabels,
  renameFaceCluster,
} from "@/lib/api";
import type { FaceCluster } from "@/lib/api";

import type { FilterState } from "./types";

/**
 * One person in the people filter: their face, their name, and a way to set it.
 *
 * The list previously showed a truncated cluster UUID, which gave no way to tell who a
 * person was. Names live on the global cluster, so naming someone here also names them
 * in every album made later.
 */
function PersonTile({
  cluster,
  index,
  active,
  onToggle,
}: {
  cluster: FaceCluster;
  index: number;
  active: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(cluster.name ?? "");
  const [failed, setFailed] = useState(false);

  const rename = useMutation({
    mutationFn: (name: string | null) => renameFaceCluster(cluster.id, name),
    onSuccess: () => {
      setEditing(false);
      setFailed(false);
      void qc.invalidateQueries({ queryKey: ["face-clusters"] });
    },
    onError: () => setFailed(true),
  });

  const label = cluster.name ?? t("filter.personN", { number: index + 1 });

  return (
    <div className="flex flex-col items-center gap-1">
      <button
        type="button"
        onClick={onToggle}
        title={label}
        aria-pressed={active}
        className={`relative w-full aspect-square overflow-hidden rounded-lg border-2 ${
          active ? "border-indigo-600" : "border-transparent hover:border-gray-300"
        }`}
      >
        <img
          src={faceClusterThumbUrl(cluster.id)}
          alt={label}
          loading="lazy"
          className="w-full h-full object-cover bg-gray-100"
        />
        <span
          className="absolute bottom-0 inset-x-0 bg-black/55 text-white text-[10px]
                     leading-4 text-center"
        >
          {cluster.face_count}
        </span>
      </button>

      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => rename.mutate(draft.trim() || null)}
          onKeyDown={(e) => {
            if (e.key === "Enter") rename.mutate(draft.trim() || null);
            if (e.key === "Escape") {
              setDraft(cluster.name ?? "");
              setEditing(false);
            }
          }}
          placeholder={t("filter.namePlaceholder")}
          className="w-full rounded border border-gray-300 px-1 py-0.5 text-[11px] text-center"
        />
      ) : (
        <button
          type="button"
          onClick={() => {
            setDraft(cluster.name ?? "");
            setEditing(true);
          }}
          className={`w-full truncate text-[11px] hover:underline ${
            cluster.name ? "text-gray-800" : "text-gray-400"
          }`}
          title={t("filter.nameThisPerson")}
        >
          {label}
        </button>
      )}
      {failed && <span className="text-[10px] text-red-600">{t("filter.nameFailed")}</span>}
    </div>
  );
}

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
          <div className="grid grid-cols-3 gap-2">
            {clustersQ.data.map((c, i) => (
              <PersonTile
                key={c.id}
                cluster={c}
                index={i}
                active={selectedPeople.has(c.id)}
                onToggle={() => toggleId("person_cluster_ids", c.id)}
              />
            ))}
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
