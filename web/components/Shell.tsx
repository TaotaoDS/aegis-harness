"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Sidebar } from "./Sidebar";
import { useAuth } from "@/lib/auth/context";
import { useT } from "@/lib/i18n";
import type { ReactNode } from "react";

/** Paths that do not require authentication. */
const PUBLIC_PATHS = ["/login", "/register"];

function isPublicPath(pathname: string): boolean {
  if (PUBLIC_PATHS.includes(pathname)) return true;
  // /invite/* is also public
  if (pathname.startsWith("/invite/")) return true;
  return false;
}

export function Shell({ children }: { children: ReactNode }) {
  const t = useT();
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  // Route guard: redirect unauthenticated users to /login
  useEffect(() => {
    if (loading) return;
    if (!user && !isPublicPath(pathname)) {
      router.replace("/login");
    }
  }, [loading, user, pathname, router]);

  // Auth pages render full-screen (no sidebar)
  if (isPublicPath(pathname)) {
    return <>{children}</>;
  }

  // Onboarding is a full-screen wizard — no sidebar
  if (pathname?.startsWith("/onboarding")) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8">
        <div className="w-full max-w-2xl">{children}</div>
      </div>
    );
  }

  // Show a minimal loading veil while the auth check is in flight
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#060d1a]">
        <p className="text-sm text-slate-400">{t.auth.sessionLoading}</p>
      </div>
    );
  }

  // Unauthenticated on a protected path — blank while redirect is pending
  if (!user) return null;

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 min-h-screen overflow-y-auto pl-52">
        <div className="px-8 py-8 max-w-6xl">
          {children}
        </div>
      </main>
    </div>
  );
}
