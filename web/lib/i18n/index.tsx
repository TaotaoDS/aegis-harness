"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { zh } from "./zh";
import { en } from "./en";
import type { Translations } from "./zh";

type Locale = "zh" | "en";

const DICTS: Record<Locale, Translations> = { zh, en };

interface LocaleCtx {
  locale: Locale;
  setLocale: (l: Locale) => void;
}

const LocaleContext = createContext<LocaleCtx>({ locale: "zh", setLocale: () => {} });

function detectLocale(): Locale {
  if (typeof navigator === "undefined") return "zh";
  const lang =
    (navigator.languages && navigator.languages[0]) || navigator.language || "zh";
  return lang.toLowerCase().startsWith("zh") ? "zh" : "en";
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  // Default to "zh" to avoid SSR mismatch; switch after mount
  const [locale, setLocale] = useState<Locale>("zh");

  useEffect(() => {
    setLocale(detectLocale());
  }, []);

  const value = useMemo(() => ({ locale, setLocale }), [locale]);

  return (
    <LocaleContext.Provider value={value}>
      {children}
    </LocaleContext.Provider>
  );
}

export function useLocale(): LocaleCtx {
  return useContext(LocaleContext);
}

export function useT(): Translations {
  const { locale } = useLocale();
  return DICTS[locale];
}
