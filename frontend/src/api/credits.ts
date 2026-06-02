import api from './client'

export interface CreditBalance {
  balance: number
  daily_free_allowance: number
  last_daily_reset: string | null
}

export interface CreditTransaction {
  id: string
  amount: number
  balance_after: number
  transaction_type: string
  description: string | null
  created_at: string
}

export interface CreditHistory {
  transactions: CreditTransaction[]
  total: number
}

export const creditsApi = {
  getBalance: () => api.get<CreditBalance>('/credits/balance'),
  getHistory: (page = 1, pageSize = 20) =>
    api.get<CreditHistory>('/credits/history', {
      params: { page, page_size: pageSize },
    }),
}
