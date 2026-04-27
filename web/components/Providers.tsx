"use client";

import { LocaleProvider } from "@/lib/i18n";
import { AuthProvider }   from "@/lib/auth/context";
import { ThemeProvider }  from "@/lib/theme/context";
import type { ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider>
      <LocaleProvider>
        <AuthProvider>{children}</AuthProvider>
      </LocaleProvider>
    </ThemeProvider>
  );
}
