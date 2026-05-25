import { create } from 'zustand'
import { Conversation, Message, SSEEvent } from '@/api/chat'

interface ChatState {
  conversations: Conversation[]
  currentConversation: Conversation | null
  messages: Message[]
  streamingContent: string
  toolEvents: SSEEvent[]
  isStreaming: boolean
  setConversations: (conversations: Conversation[]) => void
  setCurrentConversation: (conv: Conversation | null) => void
  setMessages: (messages: Message[]) => void
  appendStreamDelta: (delta: string) => void
  addToolEvent: (event: SSEEvent) => void
  setIsStreaming: (v: boolean) => void
  resetStream: () => void
}

export const useChatStore = create<ChatState>((set) => ({
  conversations: [],
  currentConversation: null,
  messages: [],
  streamingContent: '',
  toolEvents: [],
  isStreaming: false,

  setConversations: (conversations) => set({ conversations }),
  setCurrentConversation: (conv) => set({ currentConversation: conv }),
  setMessages: (messages) => set({ messages }),
  appendStreamDelta: (delta) =>
    set((state) => ({ streamingContent: state.streamingContent + delta })),
  addToolEvent: (event) =>
    set((state) => ({ toolEvents: [...state.toolEvents, event] })),
  setIsStreaming: (v) => set({ isStreaming: v }),
  resetStream: () => set({ streamingContent: '', toolEvents: [], isStreaming: false }),
}))
