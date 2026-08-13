import { render, screen } from "@testing-library/react"
import { BrainCircuit } from "lucide-react"

import {
  ProviderBrandIcon,
  resolveProviderBrand,
} from "@/features/settings/provider-brand-icon"
import { settingsSections } from "@/features/settings/settings-sections"

describe("provider brand identity", () => {
  it.each([
    [{ providerType: "openrouter", baseUrl: "https://api.openai.com/v1", name: "Custom" }, "openrouter"],
    [{ providerType: "openai_compatible", baseUrl: "https://OPENROUTER.AI/api/v1", name: "Custom" }, "openrouter"],
    [{ providerType: "openai_compatible", baseUrl: "https://api.openai.com/v1", name: "Custom" }, "openai"],
    [{ providerType: "openai_compatible", baseUrl: "https://example.openai.azure.com", name: "Custom" }, "azure-openai"],
    [{ providerType: "openai_compatible", baseUrl: "https://api.anthropic.com", name: "Custom" }, "anthropic"],
    [{ providerType: "openai_compatible", baseUrl: "https://generativelanguage.googleapis.com/v1", name: "Custom" }, "gemini"],
    [{ providerType: "openai_compatible", baseUrl: "https://api.groq.com/openai/v1", name: "Custom" }, "groq"],
    [{ providerType: "openai_compatible", baseUrl: "https://api.mistral.ai/v1", name: "Custom" }, "mistral"],
    [{ providerType: "openai_compatible", baseUrl: "https://api.x.ai/v1", name: "Custom" }, "xai"],
    [{ providerType: "openai_compatible", baseUrl: "https://api.together.xyz/v1", name: "Custom" }, "together"],
    [{ providerType: "openai_compatible", baseUrl: "https://api.fireworks.ai/inference/v1", name: "Custom" }, "fireworks"],
    [{ providerType: "openai_compatible", baseUrl: "https://api.cohere.ai/v1", name: "Custom" }, "cohere"],
    [{ providerType: "openai_compatible", baseUrl: "https://api.perplexity.ai", name: "Custom" }, "perplexity"],
    [{ providerType: "openai_compatible", baseUrl: "not a URL", name: "  DeepSeek Newsroom  " }, "deepseek"],
    [{ providerType: "openai_compatible", baseUrl: "http://localhost:11434/v1", name: "Ollama local" }, "ollama"],
    [{ providerType: "openai_compatible", baseUrl: "http://localhost:1234/v1", name: "LM Studio" }, "lm-studio"],
    [{ providerType: "openai_compatible", baseUrl: "https://llm.example/v1", name: "Private endpoint" }, "generic"],
  ] as const)("resolves normalized provider metadata", (identity, expected) => {
    expect(resolveProviderBrand(identity)).toBe(expected)
  })

  it("renders decorative fixed-size brand marks with a neutral unknown fallback", () => {
    const { rerender } = render(
      <div aria-label="OpenRouter provider">
        <ProviderBrandIcon baseUrl="https://openrouter.ai/api/v1" className="size-5" name="Route" />
      </div>,
    )
    const openRouter = screen.getByLabelText("OpenRouter provider").querySelector("[data-provider-brand]")
    expect(openRouter).toHaveAttribute("data-provider-brand", "openrouter")
    expect(openRouter).toHaveAttribute("aria-hidden", "true")
    expect(openRouter).toHaveAttribute("data-logo-source", "lobehub-icons")
    expect(openRouter).toHaveClass("size-5")

    rerender(
      <div aria-label="Unknown provider">
        <ProviderBrandIcon baseUrl="https://private.example/v1" className="size-5" name="Custom" />
      </div>,
    )
    expect(screen.getByLabelText("Unknown provider").querySelector("svg"))
      .toHaveAttribute("data-provider-brand", "generic")
  })

  it("leaves the main LLM Providers navigation icon generic", () => {
    expect(settingsSections.find(({ id }) => id === "llm-providers")?.icon).toBe(BrainCircuit)
  })
})
