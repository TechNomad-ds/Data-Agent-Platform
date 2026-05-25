import api from './client'

export interface DataSpace {
  id: string
  name: string
  description: string | null
  index_status: string
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

export const dataSpacesApi = {
  list: () => api.get<DataSpace[]>('/data-spaces'),
  get: (id: string) => api.get<DataSpaceDetail>(`/data-spaces/${id}`),
  create: (data: { name: string; description?: string }) =>
    api.post<DataSpace>('/data-spaces', data),
  update: (id: string, data: { name?: string; description?: string }) =>
    api.put<DataSpace>(`/data-spaces/${id}`, data),
  delete: (id: string) => api.delete(`/data-spaces/${id}`),
  addFiles: (id: string, fileIds: string[]) =>
    api.post(`/data-spaces/${id}/files`, { file_ids: fileIds }),
  removeFile: (spaceId: string, fileId: string) =>
    api.delete(`/data-spaces/${spaceId}/files/${fileId}`),
  buildIndex: (id: string) => api.post(`/data-spaces/${id}/index/build`),
  uploadFiles: (spaceId: string, formData: FormData) =>
    api.post(`/data-spaces/${spaceId}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
}
