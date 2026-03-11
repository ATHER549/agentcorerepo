import type { ChatMessageType } from "../../../../../types/chat";

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

/**
 * Sorts chat messages by timestamp with proper handling of identical timestamps.
 *
 * Primary sort: By timestamp (chronological order)
 * Secondary sort: When timestamps are identical, User messages (isSend=true) come before AI/Machine messages (isSend=false)
 *
 * This ensures proper conversation agent even when backend generates identical timestamps
 * due to streaming, load balancing, or database precision limitations.
 *
 * @param a - First chat message to compare
 * @param b - Second chat message to compare
 * @returns Sort comparison result (-1, 0, 1)
 */
const sortSenderMessages = (a: ChatMessageType, b: ChatMessageType): number => {
  // Parse timestamps as UTC to handle inconsistent formats from backend
  const timeA = parseTimestampAsUTC(a.timestamp);
  const timeB = parseTimestampAsUTC(b.timestamp);

  // Primary sort: by timestamp
  if (timeA !== timeB) {
    return timeA - timeB;
  }

  // Secondary sort: if timestamps are identical, User messages come before AI/Machine
  // This ensures proper chronological order when backend generates identical timestamps
  if (a.isSend && !b.isSend) {
    return -1; // User message (isSend=true) comes first
  }
  if (!a.isSend && b.isSend) {
    return 1; // User message (isSend=true) comes first
  }

  return 0; // Keep original order for same sender types
};

export default sortSenderMessages;
