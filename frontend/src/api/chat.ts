import api from './client'
import { getValidToken } from './client'

export interface Conversation {
  id: string
  data_space_id: string | null
  data_space_ids: string[] | null
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
  type: 'text' | 'tool_use' | 'tool_result' | 'thinking' | 'error' | 'done' | 'saved' | 'conversation_deleted' | 'plan'
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
  // P1: 工具调用的人话进度描述（后端权威生成）
  summary?: string
  // P1: 工具结果诚实截断标注
  truncated?: boolean
  total_chars?: number
  shown_chars?: number
  // P2: 计划/进度步骤
  steps?: Array<{ content: string; status: 'pending' | 'in_progress' | 'completed' }>
}

export const chatApi = {
  listConversations: () => api.get<Conversation[]>('/chat/conversations'),
  getConversation: (id: string) => api.get<ConversationDetail>(`/chat/conversations/${id}`),
  createConversation: (data: { data_space_id?: string; data_space_ids?: string[]; model_id: string; title?: string }) =>
    api.post<Conversation>('/chat/conversations', data),
  deleteConversation: (id: string) => api.delete(`/chat/conversations/${id}`),
  renameConversation: (id: string, title: string) =>
    api.patch<Conversation>(`/chat/conversations/${id}`, { title }),
  persistToSpace: (id: string, data: { data_space_id?: string; message_ids?: string[] }) =>
    api.post<{ ok: boolean; filename: string; data_space_id: string; message_count: number }>(
      `/chat/conversations/${id}/persist-to-space`,
      data
    ),

  sendMessage: async (conversationId: string, content: string, signal?: AbortSignal, modelId?: string, dataSpaceId?: string, dataSpaceIds?: string[]): Promise<Response> => {
    const token = await getValidToken()
    const url = `/api/chat/conversations/${conversationId}/messages`
    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ content, model_id: modelId, data_space_id: dataSpaceId, data_space_ids: dataSpaceIds }),
      signal,
    })
  },
}
