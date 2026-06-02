import api from './client'

export interface ModelOption {
  id: string
  display_name: string
  model_name: string
  provider: string
  source: 'platform' | 'user'
  credit_multiplier: number | null
}

export interface ApiConfig {
  configured: boolean
  api_base_url?: string
  api_key_masked?: string
  model_mappings?: Record<string, string>
}

export const settingsApi = {
  listModels: () => api.get<ModelOption[]>('/settings/models'),

  getApiMode: () => api.get<{ mode: string }>('/settings/api-mode'),
  setApiMode: (mode: 'credits' | 'own_api') => api.put('/settings/api-mode', { mode }),

  getApiConfig: () => api.get<ApiConfig>('/settings/api-config'),
  saveApiConfig: (data: { api_base_url: string; api_key: string }) => api.put<ApiConfig>('/settings/api-config', data),
  deleteApiConfig: () => api.delete('/settings/api-config'),

  addMapping: (platform_model_id: string, api_model_name: string) =>
    api.post<{ model_mappings: Record<string, string> }>('/settings/api-config/mappings', { platform_model_id, api_model_name }),
  deleteMapping: (modelId: string) =>
    api.delete<{ model_mappings: Record<string, string> }>(`/settings/api-config/mappings/${modelId}`),
}
