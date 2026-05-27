import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { photoThumbUrl, searchPhotos } from "@/lib/api";

import type { FilterState } from "./types";
import { toSearchRequest } from "./types";

interface Props {
  filter: FilterState;
}

export function PhotoGrid({ filter }: Props) {
  const { t } = useTranslation();
  const req = toSearchRequest(filter);
  const q = useQuery({
    queryKey: ["photos", "search", req],
    queryFn: () => searchPhotos(req),
  });

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

  return (
    <div className="flex-1 min-w-0">
      <p className="text-xs text-gray-500 mb-3">{t("filter.results", { count: data.total })}</p>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
        {data.items.map((photo) => (
          <a
            key={photo.id}
            href={photoThumbUrl(photo.id).replace("/thumb", "/file")}
            target="_blank"
            rel="noreferrer"
            className="aspect-square overflow-hidden rounded bg-gray-100 hover:opacity-80 transition"
          >
            <img
              src={photoThumbUrl(photo.id)}
              alt=""
              loading="lazy"
              className="w-full h-full object-cover"
            />
          </a>
        ))}
      </div>
    </div>
  );
}
