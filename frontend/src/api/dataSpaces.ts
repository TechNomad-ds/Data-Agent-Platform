import api from './client'

export interface DataSpace {
  id: string
  name: string
  description: string | null
  file_count: number
  created_at: string
  updated_at: string
}

export interface FileInSpace {
  file_id: string
  filename: string
  file_type: string
  file_size: number
  added_at: string
}

export interface DataSpaceDetail extends DataSpace {
  files: FileInSpace[]
}

export interface ProcessingStatus {
  total_files: number
  ready: number
  processing: number
  error: number
  all_ready: boolean
}

export const dataSpacesApi = {
  list: () => api.get<DataSpace[]>('/data-spaces'),
  get: (id: string) => api.get<DataSpaceDetail>(`/data-spaces/${id}`),
  processingStatus: (id: string) =>
    api.get<ProcessingStatus>(`/data-spaces/${id}/processing-status`),
  create: (data: { name: string; description?: string }) =>
    api.post<DataSpace>('/data-spaces', data),
  update: (id: string, data: { name?: string; description?: string }) =>
    api.put<DataSpace>(`/data-spaces/${id}`, data),
  delete: (id: string) => api.delete(`/data-spaces/${id}`),
  addFiles: (id: string, fileIds: string[]) =>
    api.post(`/data-spaces/${id}/files`, { file_ids: fileIds }),
  removeFile: (spaceId: string, fileId: string) =>
    api.delete(`/data-spaces/${spaceId}/files/${fileId}`),
  uploadFiles: (spaceId: string, formData: FormData) =>
    api.post(`/data-spaces/${spaceId}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      // 上传大文件/ZIP 可能远超全局 30s 超时，这里取消超时限制，
      // 交由 nginx(client_body_timeout) 与后端兜底
      timeout: 0,
    }),
}
