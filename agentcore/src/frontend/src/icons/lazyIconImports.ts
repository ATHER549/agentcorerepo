// Export the lazy loading mapping for icons
export const lazyIconsMapping = {
  AIML: () => import("@/icons/AIML").then((mod) => ({ default: mod.AIMLIcon })),
  
 Azure: () =>
    import("@/icons/Azure").then((mod) => ({ default: mod.AzureIcon })),

  
  Chroma: () =>
    import("@/icons/ChromaIcon").then((mod) => ({ default: mod.ChromaIcon })),
  
  GoogleGenerativeAI: () =>
    import("@/icons/GoogleGenerativeAI").then((mod) => ({
      default: mod.GoogleGenerativeAIIcon,
    })),
  
  GradientInfinity: () =>
    import("@/icons/GradientSparkles").then((mod) => ({
      default: mod.GradientInfinity,
    })),
  
  
  GradientUngroup: () =>
    import("@/icons/GradientSparkles").then((mod) => ({
      default: mod.GradientUngroup,
    })),
  GradientSave: () =>
    import("@/icons/GradientSparkles").then((mod) => ({
      default: mod.GradientSave,
    })),
  
  Groq: () => import("@/icons/Groq").then((mod) => ({ default: mod.GroqIcon })),
  Mcp: () => import("@/icons/MCP").then((mod) => ({ default: mod.McpIcon })),
  Mistral: () =>
    import("@/icons/mistral").then((mod) => ({ default: mod.MistralIcon })),

  Pinecone: () =>
    import("@/icons/Pinecone").then((mod) => ({ default: mod.PineconeIcon })),
  
  
  
  
  
  
 
 
  
  
  
 
};
