// Root path redirects to 智控空间 (AI Workspace) — the new default homepage.
// The actual dashboard (job history) lives at /dashboard.
import { redirect } from "next/navigation";

export default function RootPage() {
  redirect("/knowledge");
}
