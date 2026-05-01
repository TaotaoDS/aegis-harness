"use client";

import { LocaleProvider }        from "@/lib/i18n";
import { AuthProvider, useAuth } from "@/lib/auth/context";
import { ThemeProvider }         from "@/lib/theme/context";
import { SessionExpiredModal }   from "@/components/SessionExpiredModal";
import type { ReactNode } from "react";

function AuthGate({ children }: { children: ReactNode }) {
  const { sessionExpired } = useAuth();
  return (
    <>
      {children}
      {sessionExpired && <SessionExpiredModal />}
    </>
  );
}

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider>
      <LocaleProvider>
        <AuthProvider>
          <AuthGate>{children}</AuthGate>
        </AuthProvider>
      </LocaleProvider>
    </ThemeProvider>
  );
}
