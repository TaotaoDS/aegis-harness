import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "AegisHarness",
  description: "Multi-agent orchestration management console",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-[#0a0f1e] text-slate-200">
        <Providers>
          <Nav />
          <main className="container mx-auto px-6 py-8 max-w-7xl">
            {children}
          </main>
        </Providers>
      </body>
    </html>
  );
}
