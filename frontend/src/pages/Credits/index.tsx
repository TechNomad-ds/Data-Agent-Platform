import { useEffect, useState } from 'react'
import { Card, Statistic, Table, Typography, Row, Col } from 'antd'
import { WalletOutlined, ThunderboltOutlined } from '@ant-design/icons'
import api from '@/api/client'

const { Title, Text } = Typography

interface Transaction {
  id: string
  amount: number
  balance_after: number
  transaction_type: string
  description: string | null
  created_at: string
}

export default function Credits() {
  const [balance, setBalance] = useState(0)
  const [dailyAllowance, setDailyAllowance] = useState(0)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)

  useEffect(() => {
    loadBalance()
    loadHistory()
  }, [page])

  const loadBalance = async () => {
    try {
      const res = await api.get('/credits/balance')
      setBalance(res.data.balance)
      setDailyAllowance(res.data.daily_free_allowance)
    } catch {}
  }

  const loadHistory = async () => {
    try {
      const res = await api.get('/credits/history', { params: { page, page_size: 20 } })
      setTransactions(res.data.transactions)
      setTotal(res.data.total)
    } catch {}
  }

  const typeMap: Record<string, string> = {
    usage: '使用消耗',
    daily_grant: '每日赠送',
    admin_grant: '管理员调整',
    purchase: '充值',
  }

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (t: string) => new Date(t).toLocaleString('zh-CN'),
    },
    {
      title: '类型',
      dataIndex: 'transaction_type',
      key: 'transaction_type',
      render: (t: string) => typeMap[t] || t,
    },
    {
      title: '变动',
      dataIndex: 'amount',
      key: 'amount',
      render: (a: number) => (
        <Text type={a > 0 ? 'success' : 'danger'}>
          {a > 0 ? '+' : ''}{a}
        </Text>
      ),
    },
    {
      title: '余额',
      dataIndex: 'balance_after',
      key: 'balance_after',
    },
    {
      title: '说明',
      dataIndex: 'description',
      key: 'description',
      render: (d: string | null) => d || '-',
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ marginBottom: 4 }}>额度中心</Title>
        <Text type="secondary">查看额度余额和使用记录</Text>
      </div>

      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={8}>
          <Card>
            <Statistic title="当前余额" value={balance} prefix={<WalletOutlined />} suffix="点" />
          </Card>
        </Col>
        <Col xs={12} sm={8}>
          <Card>
            <Statistic title="每日免费额度" value={dailyAllowance} prefix={<ThunderboltOutlined />} suffix="点" />
          </Card>
        </Col>
      </Row>

      <Card title="使用记录">
        <Table
          columns={columns}
          dataSource={transactions}
          rowKey="id"
          pagination={{
            current: page,
            total,
            pageSize: 20,
            onChange: setPage,
          }}
        />
      </Card>
    </div>
  )
}
