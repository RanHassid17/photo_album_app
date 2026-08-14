import { photoThumbUrl } from "@/lib/api";
import type { AlbumItemRead, AlbumPageRead } from "@/lib/api";

interface Props {
  page: AlbumPageRead;
}

/**
 * Renders one album page using absolute positioning over a square-ish canvas,
 * driven by the normalized 0..1 coordinates each AlbumItem carries.
 *
 * RTL is respected by treating `comment_position: start` as the inline-start
 * edge of the item (i.e. right in he, left in en).
 */
export function PageView({ page }: Props) {
  return (
    <div
      className="relative bg-white shadow-md border border-gray-200 rounded-md mx-auto"
      style={{ width: "100%", aspectRatio: "4 / 3" }}
    >
      {page.items.map((item) => (
        <ItemBox key={item.id} item={item} />
      ))}
    </div>
  );
}

function ItemBox({ item }: { item: AlbumItemRead }) {
  const { position, comment, comment_position } = item;
  const showComment = Boolean(comment) && comment_position !== "none";

  // The caption is a flex sibling of the photo rather than an overlay: the photo gets
  // whatever space is left, so it can never sit under its own caption, and the caption
  // stays attached to the image regardless of the photo's aspect ratio.
  // In an RTL document `flex-row` already places the first child at the inline start,
  // so `start`/`end` need no physical-direction classes.
  const vertical = comment_position === "above" || comment_position === "below";
  const captionFirst = comment_position === "above" || comment_position === "start";

  const caption = showComment ? (
    <div
      className={`shrink-0 text-[10px] sm:text-xs text-gray-700 text-center truncate ${
        vertical ? "w-full" : "max-w-[30%]"
      }`}
      title={comment ?? undefined}
    >
      {comment}
    </div>
  ) : null;

  return (
    <div
      className={`absolute flex items-center gap-1 ${vertical ? "flex-col" : "flex-row"}`}
      style={{
        insetInlineStart: `${position.x * 100}%`,
        top: `${position.y * 100}%`,
        width: `${position.w * 100}%`,
        height: `${position.h * 100}%`,
        transform: position.rotation_deg
          ? `rotate(${position.rotation_deg}deg)`
          : undefined,
      }}
    >
      {captionFirst && caption}
      <img
        src={photoThumbUrl(item.photo_id)}
        alt=""
        loading="lazy"
        // object-contain mirrors the PDF renderer's letterbox fit, so the on-screen
        // preview matches the exported file.
        className="flex-1 min-h-0 min-w-0 w-full h-full object-contain rounded-sm shadow-sm"
      />
      {!captionFirst && caption}
    </div>
  );
}
