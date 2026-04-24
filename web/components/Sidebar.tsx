"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useT, useLocale } from "@/lib/i18n";

const STRIP_EMOJI = /^[\p{Emoji}\u2600-\u26FF]\s*/u;

function stripEmoji(s: string): string {
  return s.replace(STRIP_EMOJI, "");
}

export function Sidebar() {
  const t = useT();
  const { locale, setLocale } = useLocale();
  const pathname = usePathname();

  const links = [
    { href: "/",          label: stripEmoji(t.nav.dashboard), icon: "📊" },
    { href: "/chat",      label: stripEmoji(t.nav.chat),      icon: "💬" },
    { href: "/jobs/new",  label: stripEmoji(t.nav.newJob),    icon: "＋" },
    { href: "/settings",  label: stripEmoji(t.nav.settings),  icon: "⚙️" },
  ];

  function isActive(href: string): boolean {
    if (href === "/chat") return pathname === "/chat";
    if (href === "/") return pathname === "/";
    return pathname?.startsWith(href) ?? false;
  }

  return (
    <aside className="fixed top-0 left-0 w-52 h-screen bg-[#0d1526] border-r border-slate-800 flex flex-col">
      {/* Branding */}
      <div className="px-4 py-4 border-b border-slate-800 flex items-center gap-2">
        <span className="text-xl">⚙️</span>
        <span className="font-bold text-white text-base tracking-tight">AegisHarness</span>
      </div>

      {/* Nav links */}
      <nav className="flex-1 px-3 py-4 flex flex-col gap-1">
        {links.map(({ href, label, icon }) => {
          const active = isActive(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                active
                  ? "bg-blue-600/20 text-white border border-blue-500/30"
                  : "text-slate-400 hover:text-white hover:bg-slate-800"
              }`}
            >
              <span className="w-5 text-center shrink-0">{icon}</span>
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Bottom: language toggle + version */}
      <div className="px-4 py-4 border-t border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-1 text-xs text-slate-500">
          <button
            onClick={() => setLocale("zh")}
            className={`px-2 py-0.5 rounded transition-colors ${
              locale === "zh" ? "text-white bg-slate-700" : "hover:text-slate-300"
            }`}
          >
            中文
          </button>
          <span>/</span>
          <button
            onClick={() => setLocale("en")}
            className={`px-2 py-0.5 rounded transition-colors ${
              locale === "en" ? "text-white bg-slate-700" : "hover:text-slate-300"
            }`}
          >
            EN
          </button>
        </div>
        <span className="text-xs text-slate-600">v0.0.2</span>
      </div>
    </aside>
  );
}
