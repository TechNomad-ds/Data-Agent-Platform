import api from './client'

export interface ApiKeyConfig {
  id: string
  provider: string
  api_key_masked: string
  api_base_url: string | null
  model_name: string
  display_name: string
  is_active: boolean
  created_at: string
}

export interface ModelOption {
  id: string
  display_name: string
  model_name: string
  provider: string
  source: 'platform' | 'user'
  credit_multiplier: number | null
}

export interface ApiKeyCreateData {
  provider: 'anthropic' | 'openai'
  api_key: string
  api_base_url?: string
  model_name: string
  display_name: string
}

export const settingsApi = {
  listApiKeys: () => api.get<ApiKeyConfig[]>('/settings/api-keys'),
  createApiKey: (data: ApiKeyCreateData) => api.post<ApiKeyConfig>('/settings/api-keys', data),
  deleteApiKey: (id: string) => api.delete(`/settings/api-keys/${id}`),
  listModels: () => api.get<ModelOption[]>('/settings/models'),
}
