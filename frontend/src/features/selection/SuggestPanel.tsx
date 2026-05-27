import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { searchPhotos, suggestSelection } from "@/lib/api";

import { toSearchRequest } from "@/features/filter/types";
import type { FilterState } from "@/features/filter/types";
import { useSelectionStore } from "./store";

interface Props {
  filter: FilterState;
}

const DEFAULT_TARGET = 12;

export function SuggestPanel({ filter }: Props) {
  const { t } = useTranslation();
  const [target, setTarget] = useState<number>(DEFAULT_TARGET);
  const [criteria, setCriteria] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const ai = useSelectionStore((s) => s.ai);
  const setAi = useSelectionStore((s) => s.setAiSuggestion);
  const accept = useSelectionStore((s) => s.acceptAi);
  const clear = useSelectionStore((s) => s.clear);

  // We need the current filter's photo_ids to send to the agent.
  const searchReq = { ...toSearchRequest(filter), limit: 500 };
  const photosQ = useQuery({
    queryKey: ["photos", "search-for-ai", searchReq],
    queryFn: () => searchPhotos(searchReq),
  });

  const runSuggest = async () => {
    if (!photosQ.data || photosQ.data.items.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await suggestSelection({
        photo_ids: photosQ.data.items.map((p) => p.id),
        target_count: Math.max(1, Math.min(100, target)),
        criteria: criteria.trim() || undefined,
      });
      setAi(resp);
    } catch (e) {
      setError((e as Error).message);
      setAi(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4 space-y-3 mb-4">
      <h2 className="text-lg font-semibold">{t("selection.title")}</h2>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
        <label className="block text-sm text-gray-700">
          {t("selection.targetCount")}
          <input
            type="number"
            min={1}
            max={100}
            value={target}
            onChange={(e) => setTarget(Number(e.target.value) || DEFAULT_TARGET)}
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1"
          />
        </label>
        <label className="block text-sm text-gray-700 sm:col-span-2">
          {t("selection.criteria")}
          <input
            type="text"
            value={criteria}
            onChange={(e) => setCriteria(e.target.value)}
            placeholder={t("selection.criteriaPlaceholder")}
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1"
          />
        </label>
      </div>

      <div className="flex gap-2 flex-wrap">
        <button
          type="button"
          onClick={runSuggest}
          disabled={busy || !photosQ.data || photosQ.data.items.length === 0}
          className="px-3 py-1.5 rounded bg-indigo-600 text-white text-sm
                     hover:bg-indigo-700 disabled:opacity-50"
        >
          {busy ? t("selection.suggesting") : t("selection.suggest")}
        </button>
        {ai && (
          <>
            <button
              type="button"
              onClick={accept}
              className="px-3 py-1.5 rounded border border-indigo-600 text-indigo-700
                         text-sm hover:bg-indigo-50"
            >
              {t("selection.acceptAll", { count: ai.picks.length })}
            </button>
            <button
              type="button"
              onClick={() => useSelectionStore.getState().setAiSuggestion(null)}
              className="px-3 py-1.5 rounded border border-gray-300 text-gray-700
                         text-sm hover:bg-gray-50"
            >
              {t("selection.dismissAi")}
            </button>
          </>
        )}
        <button
          type="button"
          onClick={clear}
          className="px-3 py-1.5 rounded border border-gray-300 text-gray-700
                     text-sm hover:bg-gray-50"
        >
          {t("selection.clearAll")}
        </button>
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}

      {ai && (
        <div className="text-xs text-gray-600">
          {ai.used_fallback ? (
            <span className="text-amber-700">{t("selection.fallbackUsed")}</span>
          ) : (
            <span>
              {t("selection.aiSummary", { count: ai.picks.length, model: ai.model ?? "claude" })}
            </span>
          )}
        </div>
      )}
    </section>
  );
}
