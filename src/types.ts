/**
 * Type definitions for Codexter Extension
 */

// Screen types
export type Screen = "welcome" | "options" | "chat";

// Context types for AI tasks
export type Context = "testcase" | "refactoring" | null;

// Message interface for chat
export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

// Chat history structure
export interface ChatHistory {
  testcase: Message[];
  refactoring: Message[];
}

// Chrome message types
export interface ChromeMessage {
  type: string;
  code?: string;
  timestamp?: number;
  url?: string;
  data?: any;
}

// Code selection message
export interface CodeSelectedMessage extends ChromeMessage {
  type: "CODE_SELECTED";
  code: string;
  timestamp: number;
  url: string;
}

// Get stored code message
export interface GetStoredCodeMessage extends ChromeMessage {
  type: "GET_STORED_CODE";
}

// AI API call message
export interface AIAPICallMessage extends ChromeMessage {
  type: "CALL_AI_API";
  data: {
    code: string;
    context: "testcase" | "refactoring";
    prompt: string;
  };
}

// AI API response
export interface AIAPIResponse {
  success: boolean;
  result?: string;
  error?: string;
}

// Storage data structure
export interface StorageData {
  chatHistory: ChatHistory;
  lastContext: Context;
  settings: AppSettings;
}

// App settings
export interface AppSettings {
  theme?: "light" | "dark";
  autoDetectCode?: boolean;
  apiKey?: string;
  apiEndpoint?: string;
}

// Code detection result
export interface CodeDetectionResult {
  isCode: boolean;
  confidence: number;
  language?: string;
}