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

  // Reserve space for the comment block when it's adjacent to the photo.
  const commentSize = 0.12; // 12% of the cell on the chosen edge
  const imgInset = { left: 0, top: 0, right: 0, bottom: 0 };
  const showComment = comment && comment_position !== "none";

  if (showComment) {
    if (comment_position === "above") imgInset.top = commentSize;
    if (comment_position === "below") imgInset.bottom = commentSize;
    if (comment_position === "start") imgInset.left = commentSize;
    if (comment_position === "end") imgInset.right = commentSize;
  }

  return (
    <div
      className="absolute"
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
      <img
        src={photoThumbUrl(item.photo_id)}
        alt=""
        loading="lazy"
        className="absolute object-cover rounded-sm shadow-sm"
        style={{
          left: `${imgInset.left * 100}%`,
          top: `${imgInset.top * 100}%`,
          right: `${imgInset.right * 100}%`,
          bottom: `${imgInset.bottom * 100}%`,
          width: "auto",
          height: "auto",
        }}
      />
      {showComment && (
        <div
          className="absolute text-[10px] sm:text-xs text-gray-700 px-1 truncate"
          style={positionForComment(comment_position, commentSize)}
          title={comment ?? undefined}
        >
          {comment}
        </div>
      )}
    </div>
  );
}

function positionForComment(
  pos: AlbumItemRead["comment_position"],
  size: number,
): React.CSSProperties {
  const sizePct = `${size * 100}%`;
  switch (pos) {
    case "above":
      return { left: 0, right: 0, top: 0, height: sizePct, display: "flex", alignItems: "center" };
    case "below":
      return { left: 0, right: 0, bottom: 0, height: sizePct, display: "flex", alignItems: "center" };
    case "start":
      return {
        insetInlineStart: 0,
        top: 0,
        bottom: 0,
        width: sizePct,
        writingMode: "vertical-rl",
        display: "flex",
        alignItems: "center",
      };
    case "end":
      return {
        insetInlineEnd: 0,
        top: 0,
        bottom: 0,
        width: sizePct,
        writingMode: "vertical-rl",
        display: "flex",
        alignItems: "center",
      };
    default:
      return { display: "none" };
  }
}
