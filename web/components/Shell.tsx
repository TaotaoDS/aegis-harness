"use client";
import { usePathname } from "next/navigation";
import { Sidebar } from "./Sidebar";
import type { ReactNode } from "react";

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  // Onboarding is a full-screen wizard — no sidebar
  if (pathname?.startsWith("/onboarding")) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8">
        <div className="w-full max-w-2xl">{children}</div>
      </div>
    );
  }

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
