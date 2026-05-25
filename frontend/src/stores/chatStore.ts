import { create } from 'zustand'
import { Conversation, Message, SSEEvent } from '@/api/chat'

interface ChatState {
  conversations: Conversation[]
  currentConversation: Conversation | null
  messages: Message[]
  streamingContent: string
  toolEvents: SSEEvent[]
  thinkingText: string
  isStreaming: boolean
  abortController: AbortController | null
  setConversations: (conversations: Conversation[]) => void
  setCurrentConversation: (conv: Conversation | null) => void
  setMessages: (messages: Message[]) => void
  appendStreamDelta: (delta: string) => void
  addToolEvent: (event: SSEEvent) => void
  setThinkingText: (text: string) => void
  setIsStreaming: (v: boolean) => void
  setAbortController: (controller: AbortController | null) => void
  resetStream: () => void
  stopStreaming: () => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  currentConversation: null,
  messages: [],
  streamingContent: '',
  toolEvents: [],
  thinkingText: '',
  isStreaming: false,
  abortController: null,

  setConversations: (conversations) => set({ conversations }),
  setCurrentConversation: (conv) => set({ currentConversation: conv }),
  setMessages: (messages) => set({ messages }),
  appendStreamDelta: (delta) =>
    set((state) => ({ streamingContent: state.streamingContent + delta })),
  addToolEvent: (event) =>
    set((state) => ({ toolEvents: [...state.toolEvents, event] })),
  setThinkingText: (text) => set({ thinkingText: text }),
  setIsStreaming: (v) => set({ isStreaming: v }),
  setAbortController: (controller) => set({ abortController: controller }),
  resetStream: () => set({ streamingContent: '', toolEvents: [], thinkingText: '', isStreaming: false }),
  stopStreaming: () => {
    const { abortController } = get()
    if (abortController) {
      abortController.abort()
    }
    set({ isStreaming: false, abortController: null })
  },
}))
