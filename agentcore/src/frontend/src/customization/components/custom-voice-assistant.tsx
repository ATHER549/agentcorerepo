import {
  VoiceAssistant,
  type VoiceAssistantProps,
} from "@/modals/IOModal/components/chatView/chatInput/components/voice-assistant/voice-assistant";

export function CustomVoiceAssistant({
  agentId,
  setShowAudioInput,
}: VoiceAssistantProps) {
  return (
    <VoiceAssistant agentId={agentId} setShowAudioInput={setShowAudioInput} />
  );
}

export default CustomVoiceAssistant;
