import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

interface AlbumState {
  currentAlbumId: string | null;
  setCurrentAlbum: (id: string | null) => void;
}

export const useAlbumStore = create<AlbumState>()(
  persist(
    (set) => ({
      currentAlbumId: null,
      setCurrentAlbum: (id) => set({ currentAlbumId: id }),
    }),
    {
      name: "album.current",
      storage: createJSONStorage(() => sessionStorage),
    },
  ),
);
