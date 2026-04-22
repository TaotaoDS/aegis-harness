import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Enterprise Harness",
  description: "Multi-agent orchestration management console",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-[#0a0f1e] text-slate-200">
        {/* Top navigation */}
        <header className="border-b border-slate-800 bg-[#0d1526] px-6 py-3 flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-2xl">⚙️</span>
            <span className="font-bold text-white text-lg tracking-tight">
              Enterprise Harness
            </span>
          </div>
          <nav className="flex gap-6 ml-8 text-sm text-slate-400">
            <a href="/" className="hover:text-white transition-colors">任务总览</a>
            <a href="/jobs/new" className="hover:text-white transition-colors">新建任务</a>
          </nav>
        </header>

        <main className="container mx-auto px-6 py-8 max-w-7xl">
          {children}
        </main>
      </body>
    </html>
  );
}
