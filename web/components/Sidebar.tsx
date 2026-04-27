"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useT, useLocale } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/context";
import { useTheme } from "@/lib/theme/context";
import { listAllTenants } from "@/lib/auth/client";
import type { TenantSummary } from "@/lib/auth/client";

const STRIP_EMOJI = /^[\p{Emoji}☀-⛿]\s*/u;
const stripEmoji = (s: string) => s.replace(STRIP_EMOJI, "");

function roleBadgeClass(role: string): string {
  if (role === "super_admin") return "text-purple-600 bg-purple-100 dark:text-purple-400 dark:bg-purple-400/10";
  if (role === "owner")       return "text-amber-600  bg-amber-100  dark:text-amber-400  dark:bg-amber-400/10";
  if (role === "admin")       return "text-blue-600   bg-blue-100   dark:text-blue-400   dark:bg-blue-400/10";
  return "text-slate-600 bg-slate-200 dark:text-slate-400 dark:bg-slate-700";
}

// ---------------------------------------------------------------------------
// Workspace switcher (super_admin only)
// ---------------------------------------------------------------------------

function WorkspaceSwitcher({ user }: { user: { role: string; tenant: { id: string; name: string } | null } }) {
  const [open, setOpen]       = useState(false);
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const loadTenants = useCallback(async () => {
    if (user.role !== "super_admin") return;
    setLoading(true);
    try { setTenants(await listAllTenants()); } finally { setLoading(false); }
  }, [user.role]);

  function handleToggle() {
    if (!open && user.role === "super_admin") loadTenants();
    setOpen((v) => !v);
  }

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const currentName = user.tenant?.name ?? (user.role === "super_admin" ? "系统管理" : "—");

  return (
    <div ref={ref} className="relative px-3 pt-3 pb-1">
      <button
        onClick={handleToggle}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg
                   bg-stone-100 hover:bg-stone-200 border border-stone-200
                   dark:bg-slate-800/60 dark:hover:bg-slate-700/60 dark:border-slate-700/50
                   transition-colors text-xs"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-slate-500 shrink-0">🏢</span>
          <span className="text-slate-700 dark:text-slate-200 truncate">{currentName}</span>
        </div>
        <span className="text-slate-400 dark:text-slate-500 shrink-0">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="absolute left-3 right-3 top-full mt-1 bg-white dark:bg-[#111c35]
                        border border-stone-200 dark:border-slate-700 rounded-xl shadow-xl z-50
                        max-h-64 overflow-y-auto">
          {user.role !== "super_admin" ? (
            <div className="px-3 py-3 text-xs text-slate-500">仅超级管理员可切换租户</div>
          ) : loading ? (
            <div className="px-3 py-3 text-xs text-slate-500">加载中…</div>
          ) : tenants.length === 0 ? (
            <div className="px-3 py-3 text-xs text-slate-500">暂无租户</div>
          ) : (
            <>
              <div className="px-3 py-2 border-b border-stone-200 dark:border-slate-700/50">
                <p className="text-[10px] text-slate-500 uppercase tracking-wide">所有租户</p>
              </div>
              {tenants.map((t) => (
                <div
                  key={t.id}
                  className={`px-3 py-2.5 flex items-center justify-between cursor-pointer transition-colors
                              hover:bg-stone-100 dark:hover:bg-slate-700/40
                              ${t.id === user.tenant?.id ? "bg-blue-50 dark:bg-blue-600/10" : ""}`}
                >
                  <div className="min-w-0">
                    <p className="text-xs text-slate-900 dark:text-white truncate">{t.name}</p>
                    <p className="text-[10px] text-slate-500">{t.plan} · {t.slug}</p>
                  </div>
                  {t.id === user.tenant?.id && (
                    <span className="text-[10px] text-blue-600 dark:text-blue-400 shrink-0 ml-2">当前</span>
                  )}
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Theme toggle
// ---------------------------------------------------------------------------

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  return (
    <button
      onClick={toggleTheme}
      title={theme === "dark" ? "切换到亮色模式" : "切换到暗色模式"}
      className="text-xs px-2 py-1 rounded-md
                 text-slate-600 hover:text-slate-900 hover:bg-stone-200
                 dark:text-slate-400 dark:hover:text-white dark:hover:bg-slate-800
                 transition-colors"
    >
      {theme === "dark" ? "☀" : "🌙"}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main Sidebar
// ---------------------------------------------------------------------------

export function Sidebar() {
  const t = useT();
  const { locale, setLocale } = useLocale();
  const { user, logout }      = useAuth();
  const pathname              = usePathname();
  const router                = useRouter();

  const isSuperAdmin   = user?.role === "super_admin";
  const isAdminOrOwner = isSuperAdmin || user?.role === "owner" || user?.role === "admin";

  // Menu order matches the design spec — 智控空间 sits at the top as primary entry
  const links = [
    { href: "/knowledge",  label: t.nav.workspace,             icon: "🤖" },
    { href: "/dashboard",  label: t.nav.dashboard,             icon: "📋" },
    ...(isSuperAdmin   ? [{ href: "/admin",   label: t.nav.sysAdmin,    icon: "🛠️" }] : []),
    ...(isSuperAdmin   ? [{ href: "/admin",   label: t.nav.userApprove, icon: "👤" }] : []),
    ...(isAdminOrOwner ? [{ href: "/console", label: t.nav.console,     icon: "📈" }] : []),
    { href: "/settings",   label: stripEmoji(t.nav.settings),  icon: "⚙️" },
  ];

  function isActive(href: string, label: string): boolean {
    if (href === "/knowledge") return pathname?.startsWith("/knowledge") ?? false;
    if (href === "/dashboard") return pathname === "/dashboard";
    // The "系统管理 / System" entry is purely a section header — never active
    if (href === "/admin" && label === t.nav.sysAdmin) return false;
    return pathname?.startsWith(href) ?? false;
  }

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  function roleLabel(role: string): string {
    if (role === "super_admin") return "超级管理员";
    if (role === "owner")  return t.auth.roleOwner;
    if (role === "admin")  return t.auth.roleAdmin;
    return t.auth.roleMember;
  }

  return (
    <aside className="fixed top-0 left-0 w-52 h-screen flex flex-col
                      bg-white dark:bg-[#0d1526]
                      border-r border-stone-200 dark:border-slate-800
                      transition-colors">

      {/* Branding */}
      <div className="px-4 py-4 border-b border-stone-200 dark:border-slate-800 flex items-center gap-2">
        <span className="text-xl">⚙️</span>
        <span className="font-bold text-slate-900 dark:text-white text-base tracking-tight">
          AegisHarness
        </span>
      </div>

      {user && <WorkspaceSwitcher user={user} />}

      {/* Nav */}
      <nav className="flex-1 px-3 py-2 flex flex-col gap-1 overflow-y-auto">
        {links.map(({ href, label, icon }, idx) => {
          const active = isActive(href, label);
          return (
            <Link
              key={`${href}-${idx}`}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors
                ${active
                  ? "bg-violet-100 text-violet-900 border border-violet-300/70 font-medium dark:bg-violet-600/20 dark:text-white dark:border-violet-500/40"
                  : "text-slate-600 hover:text-slate-900 hover:bg-stone-100 dark:text-slate-400 dark:hover:text-white dark:hover:bg-slate-800 border border-transparent"
                }`}
            >
              <span className="w-5 text-center shrink-0">{icon}</span>
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-3 py-3 border-t border-stone-200 dark:border-slate-800 space-y-2">
        {user && (
          <div className="px-1 pb-1">
            <p className="text-xs text-slate-900 dark:text-white truncate font-medium" title={user.email}>
              {user.display_name || user.email}
            </p>
            <div className="flex items-center justify-between mt-1">
              <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${roleBadgeClass(user.role)}`}>
                {roleLabel(user.role)}
              </span>
              <button
                onClick={handleLogout}
                className="text-[10px] text-slate-500 hover:text-red-500 dark:hover:text-red-400 transition-colors"
              >
                {t.auth.logoutBtn}
              </button>
            </div>
          </div>
        )}

        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-1 text-xs text-slate-500">
            <button
              onClick={() => setLocale("zh")}
              className={`px-2 py-0.5 rounded transition-colors ${
                locale === "zh"
                  ? "text-slate-900 bg-stone-200 dark:text-white dark:bg-slate-700"
                  : "hover:text-slate-700 dark:hover:text-slate-300"
              }`}
            >
              中文
            </button>
            <span>/</span>
            <button
              onClick={() => setLocale("en")}
              className={`px-2 py-0.5 rounded transition-colors ${
                locale === "en"
                  ? "text-slate-900 bg-stone-200 dark:text-white dark:bg-slate-700"
                  : "hover:text-slate-700 dark:hover:text-slate-300"
              }`}
            >
              EN
            </button>
          </div>
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <span className="text-xs text-slate-400 dark:text-slate-600">v0.0.2</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
