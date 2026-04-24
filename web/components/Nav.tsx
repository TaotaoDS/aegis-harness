"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useT, useLocale } from "@/lib/i18n";

export function Nav() {
  const t = useT();
  const { locale, setLocale } = useLocale();
  const pathname = usePathname();

  const links = [
    { href: "/",        label: t.nav.dashboard },
    { href: "/chat",    label: t.nav.chat },
    { href: "/jobs/new",label: t.nav.newJob },
    { href: "/settings",label: t.nav.settings },
  ];

  return (
    <header className="border-b border-slate-800 bg-[#0d1526] px-6 py-3 flex items-center gap-4">
      <Link href="/" className="flex items-center gap-2">
        <span className="text-2xl">⚙️</span>
        <span className="font-bold text-white text-lg tracking-tight">AegisHarness</span>
      </Link>

      <nav className="flex gap-6 ml-8 text-sm text-slate-400">
        {links.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            className={`hover:text-white transition-colors ${
              pathname === href ? "text-white" : ""
            }`}
          >
            {label}
          </Link>
        ))}
      </nav>

      {/* Language toggle */}
      <div className="ml-auto flex items-center gap-1 text-xs text-slate-500">
        <button
          onClick={() => setLocale("zh")}
          className={`px-2 py-0.5 rounded transition-colors ${
            locale === "zh"
              ? "text-white bg-slate-700"
              : "hover:text-slate-300"
          }`}
        >
          中文
        </button>
        <span>/</span>
        <button
          onClick={() => setLocale("en")}
          className={`px-2 py-0.5 rounded transition-colors ${
            locale === "en"
              ? "text-white bg-slate-700"
              : "hover:text-slate-300"
          }`}
        >
          EN
        </button>
      </div>
    </header>
  );
}
