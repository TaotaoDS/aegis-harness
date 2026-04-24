/**
 * Shared provider catalogue + types for the onboarding wizard.
 * Imported by StepAPIKeys, StepModel and page.tsx.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ProviderConfig {
  apiKey: string;
  baseUrl: string;
  model: string;
}

/** Keyed by ProviderDef.id ("anthropic", "openai", "ollama", …) */
export type ProvidersState = Record<string, ProviderConfig>;

export type ProviderGroup = "global" | "china" | "local";

export interface ProviderDef {
  id: string;
  envKey: string;          // env-var name for the API key; "" for key-free providers
  label: string;
  group: ProviderGroup;
  defaultBaseUrl: string;
  suggestedModel: string;  // placeholder hint shown in the model input
  keyPlaceholder: string;  // placeholder shown in the API key input
  docsUrl: string;
  badge?: string;
  badgeClass?: string;
  noApiKey?: boolean;      // true → hide API Key field (Ollama, vLLM)
}

// ---------------------------------------------------------------------------
// Catalogue
// ---------------------------------------------------------------------------

export const ALL_PROVIDERS: ProviderDef[] = [
  // ── Global ──────────────────────────────────────────────────────────────
  {
    id: "anthropic",
    envKey: "ANTHROPIC_API_KEY",
    label: "Anthropic (Claude)",
    group: "global",
    defaultBaseUrl: "https://api.anthropic.com",
    suggestedModel: "claude-3-5-sonnet-20241022",
    keyPlaceholder: "sk-ant-api03-…",
    docsUrl: "https://console.anthropic.com/settings/keys",
    badge: "recommended",
    badgeClass: "bg-violet-900/50 text-violet-300 border-violet-700",
  },
  {
    id: "openai",
    envKey: "OPENAI_API_KEY",
    label: "OpenAI",
    group: "global",
    defaultBaseUrl: "https://api.openai.com/v1",
    suggestedModel: "gpt-4o",
    keyPlaceholder: "sk-proj-…",
    docsUrl: "https://platform.openai.com/api-keys",
  },
  {
    id: "google",
    envKey: "GOOGLE_API_KEY",
    label: "Google Gemini",
    group: "global",
    defaultBaseUrl: "https://generativelanguage.googleapis.com",
    suggestedModel: "gemini-2.0-flash",
    keyPlaceholder: "AIzaSy…",
    docsUrl: "https://aistudio.google.com/app/apikey",
  },
  {
    id: "mistral",
    envKey: "MISTRAL_API_KEY",
    label: "Mistral AI",
    group: "global",
    defaultBaseUrl: "https://api.mistral.ai/v1",
    suggestedModel: "mistral-large-latest",
    keyPlaceholder: "…",
    docsUrl: "https://console.mistral.ai/api-keys",
  },
  {
    id: "groq",
    envKey: "GROQ_API_KEY",
    label: "Groq",
    group: "global",
    defaultBaseUrl: "https://api.groq.com/openai/v1",
    suggestedModel: "llama-3.3-70b-versatile",
    keyPlaceholder: "gsk_…",
    docsUrl: "https://console.groq.com/keys",
    badge: "fast",
    badgeClass: "bg-orange-900/50 text-orange-300 border-orange-700",
  },
  {
    id: "xai",
    envKey: "XAI_API_KEY",
    label: "xAI (Grok)",
    group: "global",
    defaultBaseUrl: "https://api.x.ai/v1",
    suggestedModel: "grok-2-latest",
    keyPlaceholder: "xai-…",
    docsUrl: "https://console.x.ai/",
  },
  {
    id: "together",
    envKey: "TOGETHER_API_KEY",
    label: "Together AI",
    group: "global",
    defaultBaseUrl: "https://api.together.xyz/v1",
    suggestedModel: "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    keyPlaceholder: "…",
    docsUrl: "https://api.together.ai/settings/api-keys",
    badge: "open models",
    badgeClass: "bg-teal-900/50 text-teal-300 border-teal-700",
  },
  // ── China ────────────────────────────────────────────────────────────────
  {
    id: "deepseek",
    envKey: "DEEPSEEK_API_KEY",
    label: "DeepSeek",
    group: "china",
    defaultBaseUrl: "https://api.deepseek.com/v1",
    suggestedModel: "deepseek-chat",
    keyPlaceholder: "sk-…",
    docsUrl: "https://platform.deepseek.com/api_keys",
    badge: "cost-effective",
    badgeClass: "bg-emerald-900/50 text-emerald-300 border-emerald-700",
  },
  {
    id: "qwen",
    envKey: "DASHSCOPE_API_KEY",
    label: "Alibaba Qwen（通义千问）",
    group: "china",
    defaultBaseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    suggestedModel: "qwen-max",
    keyPlaceholder: "sk-…",
    docsUrl: "https://dashscope.console.aliyun.com/apiKey",
  },
  {
    id: "zhipu",
    envKey: "ZHIPUAI_API_KEY",
    label: "智谱 GLM（Zhipu）",
    group: "china",
    defaultBaseUrl: "https://open.bigmodel.cn/api/paas/v4",
    suggestedModel: "glm-4-flash",
    keyPlaceholder: "xxxxxxxx.xxxxxxxxxx",
    docsUrl: "https://open.bigmodel.cn/usercenter/apikeys",
  },
  {
    id: "moonshot",
    envKey: "MOONSHOT_API_KEY",
    label: "Moonshot / Kimi",
    group: "china",
    defaultBaseUrl: "https://api.moonshot.cn/v1",
    suggestedModel: "moonshot-v1-128k",
    keyPlaceholder: "sk-…",
    docsUrl: "https://platform.moonshot.cn/console/api-keys",
  },
  {
    id: "baidu",
    envKey: "BAIDU_API_KEY",
    label: "百度文心（ERNIE）",
    group: "china",
    defaultBaseUrl: "https://qianfan.baidubce.com/v2",
    suggestedModel: "ernie-4.5-8k",
    keyPlaceholder: "…",
    docsUrl: "https://qianfan.cloud.baidu.com/",
  },
  {
    id: "minimax",
    envKey: "MINIMAX_API_KEY",
    label: "MiniMax",
    group: "china",
    defaultBaseUrl: "https://api.minimax.chat/v1",
    suggestedModel: "abab6.5s-chat",
    keyPlaceholder: "…",
    docsUrl: "https://platform.minimaxi.com/user-center/basic-information/interface-key",
  },
  {
    id: "yi",
    envKey: "YI_API_KEY",
    label: "零一万物（Yi）",
    group: "china",
    defaultBaseUrl: "https://api.01.ai/v1",
    suggestedModel: "yi-large",
    keyPlaceholder: "…",
    docsUrl: "https://platform.01.ai/apikeys",
  },
  {
    id: "doubao",
    envKey: "ARK_API_KEY",
    label: "字节豆包（Doubao）",
    group: "china",
    defaultBaseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    suggestedModel: "doubao-pro-32k",
    keyPlaceholder: "…",
    docsUrl: "https://console.volcengine.com/ark/",
  },
  // ── Local / Self-hosted ──────────────────────────────────────────────────
  {
    id: "ollama",
    envKey: "",
    label: "Ollama",
    group: "local",
    defaultBaseUrl: "http://localhost:11434/v1",
    suggestedModel: "llama3.2",
    keyPlaceholder: "",
    docsUrl: "https://ollama.com/",
    noApiKey: true,
    badge: "local",
    badgeClass: "bg-slate-700/50 text-slate-300 border-slate-600",
  },
  {
    id: "vllm",
    envKey: "",
    label: "vLLM",
    group: "local",
    defaultBaseUrl: "http://localhost:8000/v1",
    suggestedModel: "Qwen/Qwen2.5-7B-Instruct",
    keyPlaceholder: "",
    docsUrl: "https://docs.vllm.ai/",
    noApiKey: true,
    badge: "local",
    badgeClass: "bg-slate-700/50 text-slate-300 border-slate-600",
  },
  {
    id: "custom",
    envKey: "CUSTOM_API_KEY",
    label: "Custom (OpenAI-compatible)",
    group: "local",
    defaultBaseUrl: "",
    suggestedModel: "",
    keyPlaceholder: "sk-…",
    docsUrl: "",
    badge: "custom",
    badgeClass: "bg-slate-700/50 text-slate-300 border-slate-600",
  },
];

// ---------------------------------------------------------------------------
// Group metadata (order matters — rendered top → bottom in sidebar)
// ---------------------------------------------------------------------------

export const PROVIDER_GROUPS: {
  key: ProviderGroup;
  labelKey: "globalProviders" | "cnProviders" | "localProviders";
}[] = [
  { key: "global", labelKey: "globalProviders" },
  { key: "china",  labelKey: "cnProviders"     },
  { key: "local",  labelKey: "localProviders"  },
];

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

/** A provider is "configured" when it has enough information to be usable. */
export function isProviderConfigured(
  id: string,
  configs: ProvidersState,
): boolean {
  const def = ALL_PROVIDERS.find((p) => p.id === id);
  if (!def) return false;
  const cfg = configs[id];
  if (!cfg) return false;
  // Local providers (no API key): need both a base URL and a model name
  if (def.noApiKey) return !!(cfg.baseUrl.trim() && cfg.model.trim());
  // Cloud providers: an API key is the minimum requirement
  return !!(cfg.apiKey.trim());
}
