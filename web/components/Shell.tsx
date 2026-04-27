"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Sidebar } from "./Sidebar";
import { useAuth } from "@/lib/auth/context";
import { checkSetupStatus } from "@/lib/auth/client";
import { useT } from "@/lib/i18n";
import type { ReactNode } from "react";

/** Paths that do not require authentication. */
const PUBLIC_PATHS = ["/login", "/register"];

function isPublicPath(pathname: string): boolean {
  if (PUBLIC_PATHS.includes(pathname)) return true;
  if (pathname.startsWith("/invite/")) return true;
  return false;
}

export function Shell({ children }: { children: ReactNode }) {
  const t = useT();
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  // One-time check on mount: does the system have a super_admin?
  const [setupChecked, setSetupChecked] = useState(false);
  const [systemReady, setSystemReady] = useState(true);

  useEffect(() => {
    checkSetupStatus().then((initialized) => {
      setSystemReady(initialized);
      setSetupChecked(true);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Guard 1: redirect to onboarding when super_admin not yet created
  useEffect(() => {
    if (!setupChecked) return;
    if (!systemReady && !pathname.startsWith("/onboarding")) {
      router.replace("/onboarding");
    }
  }, [setupChecked, systemReady, pathname, router]);

  // Guard 2: redirect unauthenticated users to /login
  useEffect(() => {
    if (!setupChecked || !systemReady) return;
    if (loading) return;
    if (!user && !isPublicPath(pathname)) {
      router.replace("/login");
    }
  }, [setupChecked, systemReady, loading, user, pathname, router]);

  // Guard 3: pending users can only see /pending
  useEffect(() => {
    if (!setupChecked || loading || !user) return;
    if (user.status === "pending" && !pathname.startsWith("/pending") && !isPublicPath(pathname)) {
      router.replace("/pending");
    }
  }, [setupChecked, loading, user, pathname, router]);

  // Auth / public pages render full-screen (no sidebar)
  if (isPublicPath(pathname)) {
    return <>{children}</>;
  }

  // Onboarding wizard (super-admin setup) — centered, no sidebar
  if (pathname?.startsWith("/onboarding")) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8 bg-stone-50 dark:bg-[#060d1a]">
        <div className="w-full max-w-md">{children}</div>
      </div>
    );
  }

  // Pending approval page — centered, no sidebar
  if (pathname?.startsWith("/pending")) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8 bg-stone-50 dark:bg-[#060d1a]">
        <div className="w-full max-w-lg">{children}</div>
      </div>
    );
  }

  // Loading veil while setup check or auth check is in flight
  if (!setupChecked || loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-stone-50 dark:bg-[#060d1a]">
        <p className="text-sm text-slate-500 dark:text-slate-400">{t.auth.sessionLoading}</p>
      </div>
    );
  }

  // Unauthenticated on a protected path — blank while redirect is pending
  if (!user) return null;

  // Pending users waiting to be redirected — blank while redirect is pending
  if (user.status === "pending") return null;

  // Full-bleed pages manage their own padding/height (no Shell wrapper padding)
  const isFullBleed = pathname?.startsWith("/knowledge");

  return (
    <div className="flex min-h-screen bg-[var(--bg-app)] text-[var(--fg-primary)]">
      <Sidebar />
      <main className={`flex-1 pl-52 ${isFullBleed ? "overflow-hidden h-screen" : "min-h-screen overflow-y-auto"}`}>
        {isFullBleed ? (
          children
        ) : (
          <div className="px-8 py-8 max-w-6xl">
            {children}
          </div>
        )}
      </main>
    </div>
  );
}
