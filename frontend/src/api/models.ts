import api from './client'

export interface ModelInfo {
  id: string
  display_name: string
  model_name: string
  provider: string
  credit_multiplier: number
}

export const modelsApi = {
  listAvailable: () => api.get<ModelInfo[]>('/models/available'),
}
