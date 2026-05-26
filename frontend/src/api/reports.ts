import api from './client'

export const reportsApi = {
  generate: (conversationId: string, format: string = 'markdown') =>
    api.post(`/reports/generate?conversation_id=${conversationId}&format=${format}`, {}, {
      responseType: 'blob',
    }),
}
