import { create } from 'zustand'
import { Conversation, Message, SSEEvent } from '@/api/chat'

export interface StreamSegment {
  type: 'text' | 'tools'
  content?: string
  events?: SSEEvent[]
}

interface ChatState {
  conversations: Conversation[]
  currentConversation: Conversation | null
  messages: Message[]
  segments: StreamSegment[]
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
  segments: [],
  thinkingText: '',
  isStreaming: false,
  abortController: null,

  setConversations: (conversations) => set({ conversations }),
  setCurrentConversation: (conv) => set({ currentConversation: conv }),
  setMessages: (messages) => set({ messages }),

  appendStreamDelta: (delta) =>
    set((state) => {
      const segs = [...state.segments]
      const last = segs[segs.length - 1]
      if (last && last.type === 'text') {
        segs[segs.length - 1] = { type: 'text', content: (last.content || '') + delta }
      } else {
        segs.push({ type: 'text', content: delta })
      }
      return { segments: segs }
    }),

  addToolEvent: (event) =>
    set((state) => {
      const segs = [...state.segments]
      const last = segs[segs.length - 1]
      if (last && last.type === 'tools') {
        segs[segs.length - 1] = { type: 'tools', events: [...(last.events || []), event] }
      } else {
        segs.push({ type: 'tools', events: [event] })
      }
      return { segments: segs }
    }),

  setThinkingText: (text) => set({ thinkingText: text }),
  setIsStreaming: (v) => set({ isStreaming: v }),
  setAbortController: (controller) => set({ abortController: controller }),

  resetStream: () => set({ segments: [], thinkingText: '', isStreaming: false }),

  stopStreaming: () => {
    const { abortController, segments, messages } = get()
    if (abortController) abortController.abort()

    const fullContent = segments.filter(s => s.type === 'text').map(s => s.content || '').join('')
    if (fullContent) {
      const assistantMsg: Message = {
        id: Date.now().toString(),
        role: 'assistant',
        content: fullContent + '\n\n[已手动停止]',
        tool_calls: segments,
        token_usage: null,
        credits_used: null,
        created_at: new Date().toISOString(),
      }
      set({ messages: [...messages, assistantMsg] })
    }
    set({ isStreaming: false, abortController: null, segments: [], thinkingText: '' })
  },
}))
