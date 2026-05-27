import api from './client'

export interface GraphNode {
  id: string
  name: string
  category: string
  symbolSize: number
}

export interface GraphEdge {
  source: string
  target: string
  name: string
}

export interface GraphExport {
  nodes: GraphNode[]
  edges: GraphEdge[]
  stats: { nodes: number; edges: number; connected_components: number }
  building?: boolean
}

export interface GraphSearchResult {
  id: string
  label: string
  type: string
  degree: number
  score: number
}

export const graphApi = {
  getStats: (spaceId: string) =>
    api.get<{ nodes: number; edges: number; connected_components: number }>(
      `/data-spaces/${spaceId}/graph/stats`
    ),

  search: (spaceId: string, query: string, topK = 10) =>
    api.get<{ query: string; results: GraphSearchResult[] }>(
      `/data-spaces/${spaceId}/graph/search?q=${encodeURIComponent(query)}&top_k=${topK}`
    ),

  getNeighbors: (spaceId: string, entity: string) =>
    api.get<{ entity: string; neighbors: Array<{ entity: string; relation: string; direction: string; label: string }> }>(
      `/data-spaces/${spaceId}/graph/neighbors/${encodeURIComponent(entity)}`
    ),

  getExport: (spaceId: string) =>
    api.get<GraphExport>(`/data-spaces/${spaceId}/graph/export`),

  buildGraph: (spaceId: string) =>
    api.post<{ status: string; message: string; file_count?: number }>(
      `/data-spaces/${spaceId}/graph/build`
    ),
}
