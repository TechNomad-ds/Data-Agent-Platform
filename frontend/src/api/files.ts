import api from './client'

export interface FileInfo {
  id: string
  filename: string
  original_filename: string
  file_type: string
  file_size: number
  mime_type: string | null
  parse_status: string
  metadata_: Record<string, unknown>
  created_at: string
}

export interface FileListResponse {
  files: FileInfo[]
  total: number
}

export const filesApi = {
  upload: (files: File[]) => {
    const formData = new FormData()
    files.forEach((f) => formData.append('files', f))
    return api.post<FileInfo[]>('/files/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  list: (page = 1, pageSize = 20, fileType?: string) =>
    api.get<FileListResponse>('/files', { params: { page, page_size: pageSize, file_type: fileType } }),
  get: (id: string) => api.get<FileInfo>(`/files/${id}`),
  delete: (id: string) => api.delete(`/files/${id}`),
}
