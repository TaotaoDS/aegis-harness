"use client";

import { LocaleProvider } from "@/lib/i18n";
import { AuthProvider } from "@/lib/auth/context";
import type { ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <LocaleProvider>
      <AuthProvider>{children}</AuthProvider>
    </LocaleProvider>
  );
}
