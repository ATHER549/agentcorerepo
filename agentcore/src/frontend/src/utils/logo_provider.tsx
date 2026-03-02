
import GoogleIcon from "@/assets/gemini_logo.svg";
import OpenAIIcon from "@/assets/openai_logo.svg";
import AnthropicIcon from "@/assets/claude_logo.svg";
import MetaIcon from "@/assets/meta_logo.svg";
import MistralIcon from "@/assets/mistral_logo.svg";
import CohereIcon from "@/assets/cohere_logo.svg";
import PerplexityIcon from "@/assets/perplexity_logo.svg";
import HuggingFaceIcon from "@/assets/huggingface_logo.svg";
import NvidiaIcon from "@/assets/nvidia_logo.svg";
import PineconeIcon from "@/assets/pinecone_logo.png";
import DefaultIcon from "@/assets/default_llm_logo.png";

// Map provider names to their icons
export const providerIcons: Record<string, string> = {
  google: GoogleIcon,
  openai: OpenAIIcon,
  anthropic: AnthropicIcon,
  meta: MetaIcon,
  mistral: MistralIcon,
  cohere: CohereIcon,
  perplexity: PerplexityIcon,
  huggingface: HuggingFaceIcon,
  nvidia: NvidiaIcon,
  pinecone: PineconeIcon,
};

// Get icon for a provider, with fallback to default
export const getProviderIcon = (provider: string): string => {
  console.log(`🟢 [getProviderIcon] Fetching icon for provider: ${provider}`);
  return providerIcons[provider.toLowerCase()] || DefaultIcon;
};