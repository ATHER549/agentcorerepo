import { create } from "zustand";
import type { MessagesStoreType } from "../types/zustand/messages";
import type { Message } from "../types/messages";

/**
 * Parse timestamp string to milliseconds, always treating as UTC.
 * Handles both "2026-01-27 17:35:51 UTC" and "2026-01-27 17:35:51" formats consistently.
 */
const parseTimestampAsUTC = (timestamp: string | undefined): number => {
  if (!timestamp) return 0;
  
  // If timestamp already has timezone info (UTC, Z, or +/-offset), parse directly
  if (timestamp.includes('UTC') || timestamp.includes('Z') || /[+-]\d{2}:\d{2}$/.test(timestamp)) {
    return new Date(timestamp).getTime();
  }
  
  // Otherwise, treat as UTC by appending 'Z' (ISO 8601 UTC designator)
  // Convert "2026-01-27 17:35:51" to "2026-01-27T17:35:51Z"
  const isoTimestamp = timestamp.replace(' ', 'T') + 'Z';
  return new Date(isoTimestamp).getTime();
};

// Helper function to sort messages by timestamp with proper handling
const sortMessagesByTimestamp = (messages: Message[]): Message[] => {
  return [...messages].sort((a, b) => {
    const timeA = parseTimestampAsUTC(a.timestamp);
    const timeB = parseTimestampAsUTC(b.timestamp);
    
    // Primary sort: by timestamp
    if (timeA !== timeB) {
      return timeA - timeB;
    }
    
    // Secondary sort: User messages come before Machine messages for same timestamp
    const isAUser = a.sender === "User";
    const isBUser = b.sender === "User";
    if (isAUser && !isBUser) return -1;
    if (!isAUser && isBUser) return 1;
    
    return 0;
  });
};

export const useMessagesStore = create<MessagesStoreType>((set, get) => ({
  displayLoadingMessage: false,
  setDisplayLoadingMessage: (value) => {
    set(() => ({ displayLoadingMessage: value }));
  },
  deleteSession: (id) => {
    set((state) => {
      const updatedMessages = state.messages.filter(
        (msg) => msg.session_id !== id,
      );
      return { messages: updatedMessages };
    });
  },
  messages: [],
  setMessages: (messages) => {
    // Sort messages by timestamp to ensure correct order
    set(() => ({ messages: sortMessagesByTimestamp(messages) }));
  },
  addMessage: (message) => {
    const existingMessage = get().messages.find((msg) => msg.id === message.id);
    if (existingMessage) {
      // Check if this is a streaming partial message (state: "partial")
      if (message.properties?.state === "partial") {
        // For streaming, accumulate the text content
        get().updateMessageText(message.id, message.text || "");
        // Update other properties but preserve accumulated text
        const { text, ...messageWithoutText } = message;
        get().updateMessagePartial(messageWithoutText);
      } else {
        // For complete messages, replace entirely and re-sort
        // This handles state change from "partial" to "complete"
        get().updateMessagePartial(message);
      }
      return;
    }
    if (message.sender === "Machine" || message.category === "error") {
      set(() => ({ displayLoadingMessage: false }));
    }
    // Add message and sort by timestamp to ensure correct order
    // (SSE events may arrive out of order)
    set(() => {
      const newMessages = [...get().messages, message];
      return { messages: sortMessagesByTimestamp(newMessages) };
    });
  },
  removeMessage: (message) => {
    set(() => ({
      messages: get().messages.filter((msg) => msg.id !== message.id),
    }));
  },
  updateMessage: (message) => {
    set(() => {
      const updatedMessages = get().messages.map((msg) =>
        msg.id === message.id ? message : msg,
      );
      // Re-sort after update to ensure correct order
      return { messages: sortMessagesByTimestamp(updatedMessages) };
    });
  },
  updateMessagePartial: (message) => {
    // search for the message and update it
    // look for the message list backwards to find the message faster
    set((state) => {
      const updatedMessages = [...state.messages];
      let needsSort = false;
      for (let i = state.messages.length - 1; i >= 0; i--) {
        if (state.messages[i].id === message.id) {
          const oldState = updatedMessages[i].properties?.state;
          updatedMessages[i] = { ...updatedMessages[i], ...message };
          // If state changed from partial to complete, we may need to re-sort
          if (oldState === "partial" && message.properties?.state === "complete") {
            needsSort = true;
          }
          break;
        }
      }
      // Re-sort if message state changed to complete (ensures final order is correct)
      return { messages: needsSort ? sortMessagesByTimestamp(updatedMessages) : updatedMessages };
    });
  },
  updateMessageText: (id, chunk) => {
    set((state) => {
      const updatedMessages = [...state.messages];
      for (let i = state.messages.length - 1; i >= 0; i--) {
        if (state.messages[i].id === id) {
          updatedMessages[i] = {
            ...updatedMessages[i],
            text: (updatedMessages[i].text || "") + chunk,
          };
          break;
        }
      }
      return { messages: updatedMessages };
    });
  },
  clearMessages: () => {
    set(() => ({ messages: [] }));
  },
  removeMessages: (ids) => {
    return new Promise((resolve, reject) => {
      try {
        set((state) => {
          const updatedMessages = state.messages.filter(
            (msg) => !ids.includes(msg.id),
          );
          get().setMessages(updatedMessages);
          resolve(updatedMessages);
          return { messages: updatedMessages };
        });
      } catch (error) {
        reject(error);
      }
    });
  },
}));
