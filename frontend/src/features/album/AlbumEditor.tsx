import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchAlbum, suggestLayout } from "@/lib/api";
import type { AlbumStyle } from "@/lib/api";

import { useSelectionStore } from "@/features/selection/store";

import { PageView } from "./PageView";
import { useAlbumStore } from "./store";

const STYLES: AlbumStyle[] = ["modern", "classic", "kids", "romantic", "minimalist"];
const DEFAULT_PAGES = 3;

export function AlbumEditor() {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const selected = useSelectionStore((s) => s.selected);
  const currentAlbumId = useAlbumStore((s) => s.currentAlbumId);
  const setCurrentAlbum = useAlbumStore((s) => s.setCurrentAlbum);

  const [style, setStyle] = useState<AlbumStyle>("modern");
  const [pageCount, setPageCount] = useState<number>(DEFAULT_PAGES);
  const [name, setName] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [pageIdx, setPageIdx] = useState<number>(0);

  const albumQ = useQuery({
    queryKey: ["album", currentAlbumId],
    queryFn: () => fetchAlbum(currentAlbumId!),
    enabled: !!currentAlbumId,
  });

  const album = albumQ.data;
  const totalPages = album?.pages.length ?? 0;
  const safePageIdx = Math.min(pageIdx, Math.max(0, totalPages - 1));

  const runSuggest = async () => {
    if (selected.length === 0) {
      setError(t("album.needSelection"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const resp = await suggestLayout({
        photo_ids: selected,
        page_count: Math.max(1, Math.min(50, pageCount)),
        style,
        name: name.trim() || undefined,
      });
      setCurrentAlbum(resp.album_id);
      setPageIdx(0);
      await qc.invalidateQueries({ queryKey: ["album", resp.album_id] });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4 mt-6 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold">{t("album.title")}</h2>
        <p className="text-xs text-gray-500">
          {t("selection.selectedCount", { count: selected.length })}
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
        <label className="block text-sm text-gray-700">
          {t("album.style")}
          <select
            value={style}
            onChange={(e) => setStyle(e.target.value as AlbumStyle)}
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1 bg-white"
          >
            {STYLES.map((s) => (
              <option key={s} value={s}>
                {t(`album.styles.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm text-gray-700">
          {t("album.pageCount")}
          <input
            type="number"
            min={1}
            max={50}
            value={pageCount}
            onChange={(e) => setPageCount(Number(e.target.value) || DEFAULT_PAGES)}
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1"
          />
        </label>
        <label className="block text-sm text-gray-700 sm:col-span-2">
          {t("album.name")}
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("album.namePlaceholder")}
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1"
          />
        </label>
      </div>

      <div className="flex gap-2 flex-wrap">
        <button
          type="button"
          onClick={runSuggest}
          disabled={busy || selected.length === 0}
          className="px-3 py-1.5 rounded bg-indigo-600 text-white text-sm
                     hover:bg-indigo-700 disabled:opacity-50"
        >
          {busy ? t("album.generating") : t("album.generate")}
        </button>
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}

      {album && (
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs text-gray-600">
            <span>
              {album.used_fallback ? (
                <span className="text-amber-700">{t("album.fallbackUsed")}</span>
              ) : (
                t("album.aiSummary", { model: album.model ?? "claude" })
              )}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPageIdx((i) => Math.max(0, i - 1))}
                disabled={safePageIdx <= 0}
                className="px-2 py-0.5 rounded border border-gray-300 disabled:opacity-40"
              >
                ‹
              </button>
              <span>
                {t("album.pageOf", { current: safePageIdx + 1, total: totalPages })}
              </span>
              <button
                type="button"
                onClick={() => setPageIdx((i) => Math.min(totalPages - 1, i + 1))}
                disabled={safePageIdx >= totalPages - 1}
                className="px-2 py-0.5 rounded border border-gray-300 disabled:opacity-40"
              >
                ›
              </button>
            </div>
          </div>

          {album.pages[safePageIdx] && <PageView page={album.pages[safePageIdx]} />}
        </div>
      )}
    </section>
  );
}
