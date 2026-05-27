import { useQuery } from "@tanstack/react-query";
import Masonry from "react-masonry-css";
import { useTranslation } from "react-i18next";

import { photoThumbUrl, searchPhotos } from "@/lib/api";

import { toSearchRequest } from "@/features/filter/types";
import type { FilterState } from "@/features/filter/types";
import { useSelectionStore } from "./store";

interface Props {
  filter: FilterState;
}

const BREAKPOINTS = { default: 5, 1280: 4, 1024: 3, 640: 2 };

export function SelectionGrid({ filter }: Props) {
  const { t } = useTranslation();
  const req = toSearchRequest(filter);
  const q = useQuery({
    queryKey: ["photos", "search", req],
    queryFn: () => searchPhotos(req),
  });

  const selected = useSelectionStore((s) => s.selected);
  const toggle = useSelectionStore((s) => s.toggle);
  const ai = useSelectionStore((s) => s.ai);

  if (q.isLoading) {
    return <div className="text-sm text-gray-500">{t("filter.loading")}</div>;
  }
  if (q.isError) {
    return <div className="text-sm text-red-600">{t("health.error")}</div>;
  }
  const data = q.data!;
  if (data.total === 0) {
    return <div className="text-sm text-gray-500">{t("filter.empty")}</div>;
  }

  const selSet = new Set(selected);
  const aiPickMap = new Map(ai?.picks.map((p) => [p.photo_id, p]) ?? []);

  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs text-gray-500">{t("filter.results", { count: data.total })}</p>
        <p className="text-xs text-gray-700 font-medium">
          {t("selection.selectedCount", { count: selected.length })}
        </p>
      </div>

      <Masonry
        breakpointCols={BREAKPOINTS}
        className="flex -ms-2"
        columnClassName="ps-2 bg-clip-padding"
      >
        {data.items.map((photo) => {
          const isSel = selSet.has(photo.id);
          const aiPick = aiPickMap.get(photo.id);
          return (
            <button
              type="button"
              key={photo.id}
              onClick={() => toggle(photo.id)}
              className={`relative block w-full mb-2 rounded overflow-hidden transition group ${
                isSel ? "ring-4 ring-indigo-500" : "ring-1 ring-gray-200"
              }`}
            >
              <img
                src={photoThumbUrl(photo.id)}
                alt=""
                loading="lazy"
                className="w-full h-auto block"
              />
              {isSel && (
                <span
                  className="absolute top-1 end-1 bg-indigo-600 text-white rounded-full
                             w-6 h-6 flex items-center justify-center text-xs font-bold"
                  aria-hidden
                >
                  ✓
                </span>
              )}
              {aiPick && (
                <span
                  className="absolute bottom-1 start-1 max-w-[90%] truncate
                             bg-amber-400/95 text-amber-950 text-[10px]
                             px-1.5 py-0.5 rounded shadow"
                  title={aiPick.reason}
                >
                  AI · {aiPick.reason}
                </span>
              )}
            </button>
          );
        })}
      </Masonry>
    </div>
  );
}
