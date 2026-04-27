"use client";

/**
 * ThemeProvider — light / dark theme manager.
 *
 *   • Persists choice to localStorage("ws-theme")
 *   • Falls back to OS preference on first visit
 *   • Toggles the `dark` class on <html> so Tailwind `dark:` variants apply
 *   • Avoids hydration mismatch by reading the stored value in a useEffect
 *     and mounting children with `suppressHydrationWarning` on <html>
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Theme = "light" | "dark";

interface ThemeCtx {
  theme:        Theme;
  setTheme:     (t: Theme) => void;
  toggleTheme:  () => void;
}

const Ctx = createContext<ThemeCtx>({
  theme: "dark",
  setTheme:    () => {},
  toggleTheme: () => {},
});

const STORAGE_KEY = "ws-theme";

function applyToDom(t: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", t === "dark");
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("dark");

  // Initialise once on the client
  useEffect(() => {
    let initial: Theme = "dark";
    try {
      const stored = localStorage.getItem(STORAGE_KEY) as Theme | null;
      if (stored === "light" || stored === "dark") {
        initial = stored;
      } else if (window.matchMedia?.("(prefers-color-scheme: light)").matches) {
        initial = "light";
      }
    } catch {
      /* SSR or storage blocked */
    }
    setThemeState(initial);
    applyToDom(initial);
  }, []);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    try { localStorage.setItem(STORAGE_KEY, t); } catch { /* ignore */ }
    applyToDom(t);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

  return (
    <Ctx.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </Ctx.Provider>
  );
}

export function useTheme() {
  return useContext(Ctx);
}
