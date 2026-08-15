import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  downloadAlbumPdf,
  downloadAlbumPrintZip,
  fetchExportQuality,
} from "@/lib/api";

interface ExportPanelProps {
  albumId: string;
}

export function ExportPanel({ albumId }: ExportPanelProps) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<null | "pdf" | "print">(null);
  const [error, setError] = useState<string | null>(null);

  const qualityQ = useQuery({
    queryKey: ["album-quality", albumId],
    queryFn: () => fetchExportQuality(albumId),
  });

  const warningPhotoCount = new Set(
    qualityQ.data?.low_resolution_warnings.map((w) => w.photo_id) ?? [],
  ).size;

  // "Largest size the pixels allow" recommended the same size for every photo, which
  // told the user nothing. The recommendation now follows each photo's prominence in
  // the layout, so summarising it as counts per size is genuinely informative.
  const recommendations = qualityQ.data?.recommended_sizes ?? [];
  const bySize = new Map<string, number>();
  for (const r of recommendations) {
    if (!r.recommended_size) continue;
    bySize.set(r.recommended_size, (bySize.get(r.recommended_size) ?? 0) + 1);
  }
  const sizeSummary = [...bySize.entries()].sort((a, b) => b[1] - a[1]);
  const limitedCount = recommendations.filter((r) => r.limited_by_resolution).length;
  const unprintableCount = recommendations.filter((r) => !r.recommended_size).length;

  const run = async (kind: "pdf" | "print") => {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "pdf") await downloadAlbumPdf(albumId);
      else await downloadAlbumPrintZip(albumId);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="rounded-md border border-gray-200 bg-gray-50 p-3 space-y-2">
      <h3 className="text-sm font-semibold text-gray-700">{t("album.export.heading")}</h3>

      {qualityQ.data && (
        <p
          className={
            warningPhotoCount > 0
              ? "text-xs text-amber-700"
              : "text-xs text-emerald-700"
          }
        >
          {warningPhotoCount > 0
            ? t("album.export.lowResWarning", { count: warningPhotoCount })
            : t("album.export.lowResOk")}
        </p>
      )}

      {sizeSummary.length > 0 && (
        <div className="text-xs text-gray-700 space-y-1">
          <p className="font-medium">{t("album.export.recommendHeading")}</p>
          <ul className="flex flex-wrap gap-2">
            {sizeSummary.map(([size, count]) => (
              <li
                key={size}
                className="rounded-full border border-gray-300 bg-white px-2 py-0.5"
              >
                {t("album.export.recommendItem", { count, size })}
              </li>
            ))}
          </ul>
          {limitedCount > 0 && (
            <p className="text-amber-700">
              {t("album.export.recommendLimited", { count: limitedCount })}
            </p>
          )}
          {unprintableCount > 0 && (
            <p className="text-red-600">
              {t("album.export.recommendUnprintable", { count: unprintableCount })}
            </p>
          )}
          <p className="text-gray-400">{t("album.export.recommendFolderHint")}</p>
        </div>
      )}

      <div className="flex gap-2 flex-wrap">
        <button
          type="button"
          onClick={() => run("pdf")}
          disabled={busy !== null}
          className="px-3 py-1.5 rounded bg-gray-800 text-white text-sm
                     hover:bg-gray-900 disabled:opacity-50"
        >
          {busy === "pdf" ? t("album.export.preparing") : t("album.export.pdf")}
        </button>
        <button
          type="button"
          onClick={() => run("print")}
          disabled={busy !== null}
          className="px-3 py-1.5 rounded border border-gray-400 bg-white text-sm
                     hover:bg-gray-100 disabled:opacity-50"
        >
          {busy === "print" ? t("album.export.preparing") : t("album.export.print")}
        </button>
      </div>

      {error && (
        <p className="text-xs text-red-600">
          {t("album.export.failed", { message: error })}
        </p>
      )}
    </div>
  );
}
