import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { Shell } from "@/components/Shell";

export const metadata: Metadata = {
  title: "AegisHarness · 智控空间",
  description: "Multi-agent orchestration management console",
};

// Tiny inline script to apply the saved theme **before** React hydrates,
// preventing a flash of wrong theme on first paint.
const themeBootstrap = `
(function(){
  try {
    var t = localStorage.getItem('ws-theme');
    if (t !== 'light' && t !== 'dark') {
      t = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    if (t === 'dark') document.documentElement.classList.add('dark');
  } catch(_) {}
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrap }} />
      </head>
      <body className="min-h-screen bg-[var(--bg-app)] text-[var(--fg-primary)]">
        <Providers>
          <Shell>{children}</Shell>
        </Providers>
      </body>
    </html>
  );
}
