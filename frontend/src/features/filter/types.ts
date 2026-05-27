import type { PhotoSearchRequest } from "@/lib/api";

export type FilterState = Pick<
  PhotoSearchRequest,
  "person_cluster_ids" | "animal_labels" | "date_from" | "date_to"
>;

export const emptyFilter: FilterState = {};

export function toSearchRequest(state: FilterState): PhotoSearchRequest {
  return {
    person_cluster_ids: state.person_cluster_ids?.length ? state.person_cluster_ids : undefined,
    animal_labels: state.animal_labels?.length ? state.animal_labels : undefined,
    date_from: state.date_from || undefined,
    date_to: state.date_to || undefined,
    limit: 120,
    offset: 0,
  };
}
