import api from './client'
import { getValidToken } from './client'

export interface Conversation {
  id: string
  data_space_id: string | null
  title: string | null
  model_id: string
  created_at: string
  updated_at: string
}

export interface Message {
  id: string
  role: string
  content: string | null
  tool_calls: any[] | null
  token_usage: unknown | null
  credits_used: number | null
  created_at: string
  segments?: any[]
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
}

export interface SSEEvent {
  type: 'text' | 'tool_use' | 'tool_result' | 'thinking' | 'error' | 'done' | 'saved' | 'conversation_deleted'
  delta?: string
  name?: string
  input?: Record<string, unknown>
  content?: string
  is_error?: boolean
  message?: string
  usage?: { input_tokens: number; output_tokens: number }
  credits_used?: number
  tool_calls_log?: Array<{ name: string; input: Record<string, unknown>; output_preview: string }>
  id?: string
  message_id?: string
}

export const chatApi = {
  listConversations: () => api.get<Conversation[]>('/chat/conversations'),
  getConversation: (id: string) => api.get<ConversationDetail>(`/chat/conversations/${id}`),
  createConversation: (data: { data_space_id?: string; model_id: string; title?: string }) =>
    api.post<Conversation>('/chat/conversations', data),
  deleteConversation: (id: string) => api.delete(`/chat/conversations/${id}`),
  renameConversation: (id: string, title: string) =>
    api.patch<Conversation>(`/chat/conversations/${id}`, { title }),

  sendMessage: async (conversationId: string, content: string, signal?: AbortSignal, modelId?: string): Promise<Response> => {
    const token = await getValidToken()
    const url = `/api/chat/conversations/${conversationId}/messages`
    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ content, model_id: modelId }),
      signal,
    })
  },
}
