const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export const apiBaseUrl = BASE_URL;

export interface Health {
  status: string;
  service: string;
  version: string;
}

export async function fetchHealth(): Promise<Health> {
  const r = await fetch(`${BASE_URL}/healthz`);
  if (!r.ok) throw new Error(`Health check failed: ${r.status}`);
  return (await r.json()) as Health;
}

// ---------- Photos ----------

export interface GpsBoundingBox {
  min_lat: number;
  max_lat: number;
  min_lng: number;
  max_lng: number;
}

export interface PhotoSearchRequest {
  person_cluster_ids?: string[];
  animal_labels?: string[];
  date_from?: string;
  date_to?: string;
  gps_bbox?: GpsBoundingBox;
  limit?: number;
  offset?: number;
}

export interface PhotoSummary {
  id: string;
  taken_at: string | null;
  gps_lat: number | null;
  gps_lng: number | null;
  width: number | null;
  height: number | null;
  blur_score: number | null;
  indexed_at: string | null;
}

export interface PhotoSearchResponse {
  total: number;
  items: PhotoSummary[];
  limit: number;
  offset: number;
}

export async function searchPhotos(req: PhotoSearchRequest): Promise<PhotoSearchResponse> {
  const r = await fetch(`${BASE_URL}/api/photos/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error(`Search failed: ${r.status}`);
  return (await r.json()) as PhotoSearchResponse;
}

export function photoThumbUrl(photoId: string): string {
  return `${BASE_URL}/api/photos/${photoId}/thumb`;
}

export function photoFileUrl(photoId: string): string {
  return `${BASE_URL}/api/photos/${photoId}/file`;
}

// ---------- Face clusters ----------

export interface FaceCluster {
  id: string;
  name: string | null;
  representative_photo_id: string | null;
  face_count: number;
}

export async function fetchFaceClusters(): Promise<FaceCluster[]> {
  const r = await fetch(`${BASE_URL}/api/face-clusters`);
  if (!r.ok) throw new Error(`Face clusters failed: ${r.status}`);
  return (await r.json()) as FaceCluster[];
}

// ---------- Labels ----------

export interface LabelCount {
  label: string;
  photo_count: number;
}

export async function fetchLabels(): Promise<LabelCount[]> {
  const r = await fetch(`${BASE_URL}/api/labels`);
  if (!r.ok) throw new Error(`Labels failed: ${r.status}`);
  return (await r.json()) as LabelCount[];
}

// ---------- Selection ----------

export interface SuggestRequest {
  photo_ids: string[];
  target_count: number;
  criteria?: string;
}

export interface SuggestPick {
  photo_id: string;
  score: number;
  reason: string;
}

export interface SuggestResponse {
  picks: SuggestPick[];
  used_fallback: boolean;
  model: string | null;
}

export async function suggestSelection(req: SuggestRequest): Promise<SuggestResponse> {
  const r = await fetch(`${BASE_URL}/api/selection/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error(`Suggest failed: ${r.status}`);
  return (await r.json()) as SuggestResponse;
}

// ---------- Layouts / Albums ----------

export type AlbumStyle = "modern" | "classic" | "kids" | "romantic" | "minimalist";
export type CommentPosition = "above" | "below" | "start" | "end" | "none";

export interface LayoutPosition {
  x: number;
  y: number;
  w: number;
  h: number;
  rotation_deg: number;
}

export interface LayoutItem {
  photo_id: string;
  position: LayoutPosition;
  comment: string | null;
  comment_position: CommentPosition;
}

export interface LayoutGrid {
  rows: number;
  cols: number;
  gap: number;
}

export interface LayoutPage {
  grid: LayoutGrid;
  items: LayoutItem[];
}

export interface LayoutPlan {
  pages: LayoutPage[];
}

export interface SuggestLayoutRequest {
  photo_ids: string[];
  page_count: number;
  style: AlbumStyle;
  name?: string;
}

export interface SuggestLayoutResponse {
  album_id: string;
  layout: LayoutPlan;
  used_fallback: boolean;
  model: string | null;
}

export async function suggestLayout(req: SuggestLayoutRequest): Promise<SuggestLayoutResponse> {
  const r = await fetch(`${BASE_URL}/api/layouts/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error(`Layout suggest failed: ${r.status}`);
  return (await r.json()) as SuggestLayoutResponse;
}

export interface AlbumItemRead {
  id: string;
  photo_id: string;
  position_index: number;
  position: LayoutPosition;
  comment: string | null;
  comment_position: CommentPosition;
}

export interface AlbumPageRead {
  id: string;
  index: number;
  layout_json: { rows: number; cols: number; gap: number };
  items: AlbumItemRead[];
}

export interface AlbumRead {
  id: string;
  name: string | null;
  style: AlbumStyle;
  page_count: number;
  used_fallback: boolean;
  model: string | null;
  pages: AlbumPageRead[];
}

export interface AlbumSummary {
  id: string;
  name: string | null;
  style: AlbumStyle;
  page_count: number;
  used_fallback: boolean;
}

export async function fetchAlbum(albumId: string): Promise<AlbumRead> {
  const r = await fetch(`${BASE_URL}/api/albums/${albumId}`);
  if (!r.ok) throw new Error(`Album fetch failed: ${r.status}`);
  return (await r.json()) as AlbumRead;
}

export async function fetchAlbums(): Promise<AlbumSummary[]> {
  const r = await fetch(`${BASE_URL}/api/albums`);
  if (!r.ok) throw new Error(`Albums list failed: ${r.status}`);
  return (await r.json()) as AlbumSummary[];
}
