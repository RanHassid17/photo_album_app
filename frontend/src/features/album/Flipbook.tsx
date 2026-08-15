import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { AlbumPageRead } from "@/lib/api";

import { PageView } from "./PageView";

const TURN_MS = 520;

/**
 * Single-page flipbook built from CSS 3D transforms — deliberately no library.
 *
 * react-pageflip / StPageFlip have no RTL mode, and a Hebrew album turns pages the
 * opposite way from an English one. Mirroring a library's LTR animation also mirrors the
 * text inside it, so the turn is implemented directly: the leaving page rotates about its
 * inline-start edge and `backface-visibility` reveals the page underneath.
 *
 * Pages are landscape (A4), so this turns one page at a time rather than showing a
 * two-page spread — two landscape pages side by side would be unreadably wide.
 */
interface Props {
  pages: AlbumPageRead[];
}

type Turn = { to: number; back: boolean };

export function Flipbook({ pages }: Props) {
  const { t, i18n } = useTranslation();
  const rtl = i18n.dir() === "rtl";

  const [index, setIndex] = useState(0);
  const [turn, setTurn] = useState<Turn | null>(null);

  const total = pages.length;
  const safeIndex = Math.min(index, Math.max(0, total - 1));

  const go = useCallback(
    (delta: number) => {
      if (turn) return; // ignore input mid-turn
      const to = safeIndex + delta;
      if (to < 0 || to >= total) return;

      const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      if (reduced) {
        setIndex(to);
        return;
      }
      setTurn({ to, back: delta < 0 });
    },
    [safeIndex, total, turn],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Arrow semantics follow the reading direction, not the physical key.
      if (e.key === "ArrowRight") go(rtl ? -1 : 1);
      if (e.key === "ArrowLeft") go(rtl ? 1 : -1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, rtl]);

  if (total === 0) return null;

  // While turning forward the destination is already painted underneath; turning back,
  // the current page stays put and the destination swings in over it.
  const basePage = turn && !turn.back ? pages[turn.to] : pages[safeIndex];
  const turningPage = turn ? (turn.back ? pages[turn.to] : pages[safeIndex]) : null;

  const suffix = rtl ? "rtl" : "ltr";
  const animation = turn
    ? `pa-turn-${turn.back ? "back" : "fwd"}-${suffix} ${TURN_MS}ms ease-in-out forwards`
    : undefined;

  const commit = () => {
    if (!turn) return;
    setIndex(turn.to);
    setTurn(null);
  };

  return (
    <div className="space-y-2">
      <style>{`
        @keyframes pa-turn-fwd-ltr  { from { transform: rotateY(0deg); }    to { transform: rotateY(-180deg); } }
        @keyframes pa-turn-fwd-rtl  { from { transform: rotateY(0deg); }    to { transform: rotateY(180deg); } }
        @keyframes pa-turn-back-ltr { from { transform: rotateY(-180deg); } to { transform: rotateY(0deg); } }
        @keyframes pa-turn-back-rtl { from { transform: rotateY(180deg); }  to { transform: rotateY(0deg); } }
      `}</style>

      <div
        className="relative mx-auto w-full"
        style={{ aspectRatio: "4 / 3", perspective: "1800px" }}
      >
        <div className="absolute inset-0">
          <PageView page={basePage} />
        </div>

        {turningPage && (
          <div
            className="absolute inset-0"
            style={{
              transformStyle: "preserve-3d",
              backfaceVisibility: "hidden",
              transformOrigin: rtl ? "right center" : "left center",
              animation,
            }}
            onAnimationEnd={commit}
          >
            <PageView page={turningPage} />
          </div>
        )}
      </div>

      <div className="flex items-center justify-center gap-3 text-xs text-gray-600">
        <button
          type="button"
          onClick={() => go(-1)}
          disabled={safeIndex <= 0 || !!turn}
          aria-label={t("album.prevPage")}
          className="px-2 py-0.5 rounded border border-gray-300 disabled:opacity-40"
        >
          ‹
        </button>
        <span>{t("album.pageOf", { current: safeIndex + 1, total })}</span>
        <button
          type="button"
          onClick={() => go(1)}
          disabled={safeIndex >= total - 1 || !!turn}
          aria-label={t("album.nextPage")}
          className="px-2 py-0.5 rounded border border-gray-300 disabled:opacity-40"
        >
          ›
        </button>
      </div>
    </div>
  );
}
