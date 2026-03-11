import { create } from "zustand";
import { getDiscordCount } from "../controllers/API";
import type { DarkStoreType } from "../types/zustand/dark";

const startedStars = Number(window.localStorage.getItem("githubStars")) ?? 0;

export const useDarkStore = create<DarkStoreType>((set, get) => ({
  dark: (() => {
    const stored = window.localStorage.getItem("isDark");
    return stored !== null ? JSON.parse(stored) : false;
  })(),
  stars: startedStars,
  version: "",
  latestVersion: "",
  currentReleaseVersion: "",
  refreshLatestVersion: (v: string) => {
    set(() => ({ latestVersion: v }));
  },
  refreshCurrentReleaseVersion: (v: string) => {
    set(() => ({ currentReleaseVersion: v }));
  },
  setDark: (dark) => {
    set(() => ({ dark: dark }));
    window.localStorage.setItem("isDark", dark.toString());
  },
  refreshVersion: (v) => {
    set(() => ({ version: v }));
  },
  refreshStars: () => {
    const nextStars = Number(window.localStorage.getItem("githubStars")) || 0;
    set(() => ({ stars: nextStars, lastUpdated: new Date() }));
  },
  discordCount: 0,
  refreshDiscordCount: () => {
    getDiscordCount().then((res) => {
      set(() => ({ discordCount: res }));
    });
  },
}));
