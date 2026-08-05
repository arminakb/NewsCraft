import { BrainCircuit } from "lucide-react"

import { cn } from "@/lib/utils"

export type ProviderBrand =
  | "anthropic"
  | "azure-openai"
  | "cohere"
  | "deepseek"
  | "fireworks"
  | "gemini"
  | "groq"
  | "lm-studio"
  | "mistral"
  | "ollama"
  | "openai"
  | "openrouter"
  | "perplexity"
  | "together"
  | "xai"
  | "generic"

type ProviderIdentity = {
  providerType?: string | null
  baseUrl?: string | null
  name?: string | null
}

const bundledBrandAssets: Record<Exclude<ProviderBrand, "generic">, string> = {
  anthropic: "/provider-logos/anthropic.svg",
  "azure-openai": "/provider-logos/azure-openai.svg",
  cohere: "/provider-logos/cohere.svg",
  deepseek: "/provider-logos/deepseek.svg",
  fireworks: "/provider-logos/fireworks.svg",
  gemini: "/provider-logos/gemini.svg",
  groq: "/provider-logos/groq.svg",
  "lm-studio": "/provider-logos/lmstudio.svg",
  mistral: "/provider-logos/mistral.svg",
  ollama: "/provider-logos/ollama.svg",
  openai: "/provider-logos/openai.svg",
  openrouter: "/provider-logos/openrouter.svg",
  perplexity: "/provider-logos/perplexity.svg",
  together: "/provider-logos/together.svg",
  xai: "/provider-logos/xai.svg",
}

const explicitBrands: Record<string, ProviderBrand> = {
  anthropic: "anthropic",
  azure: "azure-openai",
  azureopenai: "azure-openai",
  cohere: "cohere",
  deepseek: "deepseek",
  fireworks: "fireworks",
  fireworksai: "fireworks",
  gemini: "gemini",
  google: "gemini",
  googlegemini: "gemini",
  groq: "groq",
  lmstudio: "lm-studio",
  mistral: "mistral",
  ollama: "ollama",
  openai: "openai",
  openrouter: "openrouter",
  perplexity: "perplexity",
  together: "together",
  togetherai: "together",
  xai: "xai",
  grok: "xai",
}

function normalizedKey(value: string | null | undefined) {
  return (value ?? "")
    .normalize("NFKD")
    .toLocaleLowerCase("en-US")
    .replace(/[^a-z0-9]+/g, "")
}

function providerHostname(value: string | null | undefined) {
  if (!value) return ""
  try {
    return new URL(value).hostname.toLocaleLowerCase("en-US").replace(/^www\./, "").replace(/\.$/, "")
  } catch {
    return ""
  }
}

function hostnameIs(hostname: string, domain: string) {
  return hostname === domain || hostname.endsWith(`.${domain}`)
}

export function resolveProviderBrand({ providerType, baseUrl, name }: ProviderIdentity): ProviderBrand {
  const explicit = explicitBrands[normalizedKey(providerType)]
  if (explicit) return explicit

  const hostname = providerHostname(baseUrl)
  if (hostnameIs(hostname, "openrouter.ai")) return "openrouter"
  if (hostnameIs(hostname, "anthropic.com")) return "anthropic"
  if (hostnameIs(hostname, "openai.azure.com") || hostnameIs(hostname, "cognitiveservices.azure.com")) {
    return "azure-openai"
  }
  if (hostnameIs(hostname, "openai.com")) return "openai"
  if (hostnameIs(hostname, "generativelanguage.googleapis.com") || hostnameIs(hostname, "ai.google.dev")) {
    return "gemini"
  }
  if (hostnameIs(hostname, "groq.com")) return "groq"
  if (hostnameIs(hostname, "mistral.ai")) return "mistral"
  if (hostnameIs(hostname, "deepseek.com")) return "deepseek"
  if (hostnameIs(hostname, "x.ai")) return "xai"
  if (hostnameIs(hostname, "together.xyz") || hostnameIs(hostname, "together.ai")) return "together"
  if (hostnameIs(hostname, "fireworks.ai")) return "fireworks"
  if (hostnameIs(hostname, "cohere.ai") || hostnameIs(hostname, "cohere.com")) return "cohere"
  if (hostnameIs(hostname, "perplexity.ai")) return "perplexity"

  return explicitBrands[normalizedKey(name)] ?? matchProviderName(normalizedKey(name))
}

function matchProviderName(name: string): ProviderBrand {
  const matches: Array<[string, ProviderBrand]> = [
    ["azureopenai", "azure-openai"],
    ["openrouter", "openrouter"],
    ["googlegemini", "gemini"],
    ["gemini", "gemini"],
    ["anthropic", "anthropic"],
    ["openai", "openai"],
    ["deepseek", "deepseek"],
    ["togetherai", "together"],
    ["fireworksai", "fireworks"],
    ["perplexity", "perplexity"],
    ["lmstudio", "lm-studio"],
    ["mistral", "mistral"],
    ["cohere", "cohere"],
    ["ollama", "ollama"],
    ["groq", "groq"],
    ["grok", "xai"],
    ["xai", "xai"],
  ]
  return matches.find(([key]) => name.includes(key))?.[1] ?? "generic"
}

export function ProviderBrandIcon({
  providerType,
  baseUrl,
  name,
  className,
}: ProviderIdentity & { className?: string }) {
  const brand = resolveProviderBrand({ providerType, baseUrl, name })
  if (brand === "generic") {
    return (
      <BrainCircuit
        aria-hidden="true"
        className={className}
        data-provider-brand="generic"
        focusable="false"
        strokeWidth={1.5}
      />
    )
  }
  return <BrandMark brand={brand} className={className} />
}

function BrandMark({ brand, className }: { brand: Exclude<ProviderBrand, "generic">; className?: string }) {
  const bundledAsset = bundledBrandAssets[brand]
  return (
    <span
      aria-hidden="true"
      className={cn("inline-block shrink-0 bg-current", className)}
      data-logo-source="lobehub-icons"
      data-provider-brand={brand}
      style={{
        maskImage: `url(${bundledAsset})`,
        maskPosition: "center",
        maskRepeat: "no-repeat",
        maskSize: "contain",
        WebkitMaskImage: `url(${bundledAsset})`,
        WebkitMaskPosition: "center",
        WebkitMaskRepeat: "no-repeat",
        WebkitMaskSize: "contain",
      }}
    />
  )
}
