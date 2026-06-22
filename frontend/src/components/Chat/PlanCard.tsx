import { Typography } from 'antd'
import {
  CheckCircleFilled,
  LoadingOutlined,
  Loading3QuartersOutlined,
} from '@ant-design/icons'
import { colors } from '@/styles/tokens'

const { Text } = Typography

export interface PlanStep {
  content: string
  status: 'pending' | 'in_progress' | 'completed'
}

interface PlanCardProps {
  steps: PlanStep[]
}

export default function PlanCard({ steps }: PlanCardProps) {
  if (!steps || steps.length === 0) return null

  const done = steps.filter((s) => s.status === 'completed').length

  return (
    <div
      style={{
        borderRadius: 10,
        border: `1px solid ${colors.border}`,
        background: colors.bgSubtle,
        padding: '10px 12px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <Text style={{ fontSize: 12, fontWeight: 600, color: colors.textSecondary }}>
          任务计划
        </Text>
        <Text style={{ fontSize: 11, color: colors.textMuted }}>
          {done}/{steps.length} 已完成
        </Text>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {steps.map((step, i) => {
          let icon
          let textColor = colors.textSecondary
          if (step.status === 'completed') {
            icon = <CheckCircleFilled style={{ color: colors.success, fontSize: 13 }} />
            textColor = colors.textMuted
          } else if (step.status === 'in_progress') {
            icon = <LoadingOutlined style={{ color: colors.primary, fontSize: 13 }} spin />
          } else {
            icon = <Loading3QuartersOutlined style={{ color: colors.textMuted, fontSize: 13 }} />
          }
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ display: 'inline-flex', width: 16, justifyContent: 'center' }}>{icon}</span>
              <Text
                style={{
                  fontSize: 12,
                  color: textColor,
                  textDecoration: step.status === 'completed' ? 'line-through' : 'none',
                }}
              >
                {step.content}
              </Text>
            </div>
          )
        })}
      </div>
    </div>
  )
}
