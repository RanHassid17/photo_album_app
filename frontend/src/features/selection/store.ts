import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

export interface AiPick {
  photo_id: string;
  score: number;
  reason: string;
}

export interface AiSuggestion {
  picks: AiPick[];
  used_fallback: boolean;
  model: string | null;
}

interface SelectionState {
  selected: string[]; // photo_ids; array (not Set) so it persists cleanly
  ai: AiSuggestion | null;
  toggle: (photoId: string) => void;
  clear: () => void;
  setSelected: (ids: string[]) => void;
  setAiSuggestion: (s: AiSuggestion | null) => void;
  acceptAi: () => void;
}

export const useSelectionStore = create<SelectionState>()(
  persist(
    (set, get) => ({
      selected: [],
      ai: null,
      toggle: (photoId) => {
        const set_ = new Set(get().selected);
        if (set_.has(photoId)) set_.delete(photoId);
        else set_.add(photoId);
        set({ selected: Array.from(set_) });
      },
      clear: () => set({ selected: [], ai: null }),
      setSelected: (ids) => set({ selected: Array.from(new Set(ids)) }),
      setAiSuggestion: (s) => set({ ai: s }),
      acceptAi: () => {
        const ai = get().ai;
        if (!ai) return;
        set({ selected: ai.picks.map((p) => p.photo_id) });
      },
    }),
    {
      name: "album.selection",
      storage: createJSONStorage(() => sessionStorage),
    },
  ),
);

export function isSelected(state: SelectionState, photoId: string): boolean {
  return state.selected.includes(photoId);
}
