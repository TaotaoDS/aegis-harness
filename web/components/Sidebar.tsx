"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useT, useLocale } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/context";
import { listAllTenants } from "@/lib/auth/client";
import type { TenantSummary } from "@/lib/auth/client";

const STRIP_EMOJI = /^[\p{Emoji}☀-⛿]\s*/u;

function stripEmoji(s: string): string {
  return s.replace(STRIP_EMOJI, "");
}

function roleBadgeClass(role: string): string {
  if (role === "super_admin") return "text-purple-400 bg-purple-400/10";
  if (role === "owner")       return "text-amber-400 bg-amber-400/10";
  if (role === "admin")       return "text-blue-400 bg-blue-400/10";
  return "text-slate-400 bg-slate-700";
}

// ---------------------------------------------------------------------------
// Workspace Switcher
// ---------------------------------------------------------------------------

function WorkspaceSwitcher({ user }: { user: { role: string; tenant: { id: string; name: string } | null } }) {
  const [open, setOpen] = useState(false);
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const loadTenants = useCallback(async () => {
    if (user.role !== "super_admin") return;
    setLoading(true);
    try {
      const list = await listAllTenants();
      setTenants(list);
    } finally {
      setLoading(false);
    }
  }, [user.role]);

  // Open dropdown
  function handleToggle() {
    if (!open && user.role === "super_admin") loadTenants();
    setOpen((v) => !v);
  }

  // Close on outside click
  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const currentName = user.tenant?.name ?? (user.role === "super_admin" ? "系统管理" : "—");

  return (
    <div ref={ref} className="relative px-3 pt-3 pb-1">
      <button
        onClick={handleToggle}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-slate-800/60 border border-slate-700/50 hover:bg-slate-700/60 transition-colors text-xs"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-slate-500 shrink-0">🏢</span>
          <span className="text-slate-200 truncate">{currentName}</span>
        </div>
        <span className="text-slate-500 shrink-0">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="absolute left-3 right-3 top-full mt-1 bg-[#111c35] border border-slate-700 rounded-xl shadow-xl z-50 max-h-64 overflow-y-auto">
          {user.role !== "super_admin" ? (
            <div className="px-3 py-3 text-xs text-slate-500">仅超级管理员可切换租户</div>
          ) : loading ? (
            <div className="px-3 py-3 text-xs text-slate-500">加载中…</div>
          ) : tenants.length === 0 ? (
            <div className="px-3 py-3 text-xs text-slate-500">暂无租户</div>
          ) : (
            <>
              <div className="px-3 py-2 border-b border-slate-700/50">
                <p className="text-[10px] text-slate-500 uppercase tracking-wide">所有租户</p>
              </div>
              {tenants.map((t) => (
                <div
                  key={t.id}
                  className={`px-3 py-2.5 flex items-center justify-between hover:bg-slate-700/40 cursor-pointer transition-colors ${
                    t.id === user.tenant?.id ? "bg-blue-600/10" : ""
                  }`}
                >
                  <div className="min-w-0">
                    <p className="text-xs text-white truncate">{t.name}</p>
                    <p className="text-[10px] text-slate-500">{t.plan} · {t.slug}</p>
                  </div>
                  {t.id === user.tenant?.id && (
                    <span className="text-[10px] text-blue-400 shrink-0 ml-2">当前</span>
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
// Main Sidebar
// ---------------------------------------------------------------------------

export function Sidebar() {
  const t = useT();
  const { locale, setLocale } = useLocale();
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const isSuperAdmin   = user?.role === "super_admin";
  const isAdminOrOwner = isSuperAdmin || user?.role === "owner" || user?.role === "admin";

  const links = [
    { href: "/",          label: stripEmoji(t.nav.dashboard), icon: "📊" },
    ...(isSuperAdmin   ? [{ href: "/admin",   label: "用户审批",    icon: "👤" }] : []),
    ...(isAdminOrOwner ? [{ href: "/console", label: "控制台看板",  icon: "📈" }] : []),
    { href: "/chat",      label: stripEmoji(t.nav.chat),      icon: "💬" },
    { href: "/jobs/new",  label: stripEmoji(t.nav.newJob),    icon: "＋" },
    { href: "/settings",  label: stripEmoji(t.nav.settings),  icon: "⚙️" },
  ];

  function isActive(href: string): boolean {
    if (href === "/chat") return pathname === "/chat";
    if (href === "/")     return pathname === "/";
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
    <aside className="fixed top-0 left-0 w-52 h-screen bg-[#0d1526] border-r border-slate-800 flex flex-col">
      {/* Branding */}
      <div className="px-4 py-4 border-b border-slate-800 flex items-center gap-2">
        <span className="text-xl">⚙️</span>
        <span className="font-bold text-white text-base tracking-tight">AegisHarness</span>
      </div>

      {/* Workspace switcher */}
      {user && <WorkspaceSwitcher user={user} />}

      {/* Nav links */}
      <nav className="flex-1 px-3 py-2 flex flex-col gap-1 overflow-y-auto">
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

      {/* Bottom section */}
      <div className="px-3 py-3 border-t border-slate-800 space-y-2">
        {/* User info */}
        {user && (
          <div className="px-1 pb-1">
            <p className="text-xs text-white truncate font-medium" title={user.email}>
              {user.display_name || user.email}
            </p>
            <div className="flex items-center justify-between mt-1">
              <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${roleBadgeClass(user.role)}`}>
                {roleLabel(user.role)}
              </span>
              <button
                onClick={handleLogout}
                className="text-[10px] text-slate-500 hover:text-red-400 transition-colors"
              >
                {t.auth.logoutBtn}
              </button>
            </div>
          </div>
        )}

        {/* Language toggle + version */}
        <div className="flex items-center justify-between px-1">
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
      </div>
    </aside>
  );
}
