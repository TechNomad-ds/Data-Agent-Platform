import { Typography } from 'antd'
import { colors } from '@/styles/tokens'

const { Text } = Typography

export default function AuthBrand() {
  return (
    <div
      style={{
        flex: 1,
        background: `radial-gradient(ellipse at center, #2e2a6e 0%, #1e1b4b 50%, #0f0d2e 100%)`,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        padding: '60px 56px',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Ambient glow */}
      <div style={{
        position: 'absolute',
        top: '15%', left: '25%',
        width: 600, height: 600,
        borderRadius: '50%',
        background: `radial-gradient(circle, rgba(99,102,241,0.4) 0%, rgba(124,58,237,0.15) 40%, transparent 70%)`,
        filter: 'blur(80px)',
      }} />
      <div style={{
        position: 'absolute',
        bottom: '5%', right: '15%',
        width: 500, height: 500,
        borderRadius: '50%',
        background: `radial-gradient(circle, rgba(59,130,246,0.3) 0%, transparent 60%)`,
        filter: 'blur(60px)',
      }} />
      <div style={{
        position: 'absolute',
        top: '50%', left: '50%',
        transform: 'translate(-50%, -50%)',
        width: 300, height: 300,
        borderRadius: '50%',
        background: `radial-gradient(circle, rgba(167,139,250,0.25) 0%, transparent 70%)`,
        filter: 'blur(40px)',
      }} />

      {/* Subtle grid */}
      <div style={{
        position: 'absolute', inset: 0, opacity: 0.06,
        backgroundImage: 'linear-gradient(rgba(255,255,255,0.15) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.15) 1px, transparent 1px)',
        backgroundSize: '60px 60px',
        maskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
        WebkitMaskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
      }} />

      <div style={{ position: 'relative', zIndex: 1, textAlign: 'center', maxWidth: 460 }}>
        {/* Logo + Brand name */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: 16, marginBottom: 56,
        }}>
          <div style={{
            width: 52, height: 52, borderRadius: 16,
            background: `linear-gradient(135deg, ${colors.primary}, #7c3aed)`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 20px 60px rgba(79,70,229,0.4)',
          }}>
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none">
              <path d="M12 2.5L13.5 9L20 10.5L13.5 12L12 18.5L10.5 12L4 10.5L10.5 9L12 2.5Z" fill="#ffffff" />
            </svg>
          </div>
          <div style={{
            fontSize: 22, fontWeight: 600, letterSpacing: 3,
            color: 'rgba(255,255,255,0.6)',
            textTransform: 'uppercase',
          }}>
            DataMind
          </div>
        </div>

        {/* Hero text */}
        <h1 style={{
          fontSize: 44, fontWeight: 700, lineHeight: 1.2,
          letterSpacing: -1,
          color: '#ffffff',
          margin: '0 0 32px',
        }}>
          让数据<span style={{
            background: 'linear-gradient(135deg, #818cf8, #a78bfa, #60a5fa)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}>自己说话</span>
        </h1>

        {/* Subtitle */}
        <p style={{
          fontSize: 16, lineHeight: 1.8,
          color: 'rgba(255,255,255,0.45)',
          margin: '0 auto 64px',
          maxWidth: 340,
          fontWeight: 400,
        }}>
          上传数据，对话分析，可视化洞察
          <br />
          AI 驱动，零代码，人人可用
        </p>

        {/* Stats */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: 48 }}>
          {[
            { num: '20+', label: '数据格式' },
            { num: '14', label: 'AI 工具' },
            { num: '100%', label: '数据隔离' },
          ].map(s => (
            <div key={s.label}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#ffffff', marginBottom: 4 }}>{s.num}</div>
              <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.35)', letterSpacing: 0.5 }}>{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div style={{ position: 'absolute', bottom: 28, left: 0, right: 0, textAlign: 'center', zIndex: 1 }}>
        <Text style={{ color: 'rgba(255,255,255,0.2)', fontSize: 12 }}>
          © {new Date().getFullYear()} DataMind Platform
        </Text>
      </div>
    </div>
  )
}
