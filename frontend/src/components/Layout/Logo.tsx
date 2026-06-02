interface LogoProps {
  size?: number
  withText?: boolean
  text?: string
  textColor?: string
}

export default function Logo({
  size = 28,
  withText = true,
  text = 'DataMind',
  textColor = '#1f2328',
}: LogoProps) {
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
      <div
        style={{
          width: size,
          height: size,
          borderRadius: size * 0.25,
          background: '#4f46e5',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <svg
          width={size * 0.55}
          height={size * 0.55}
          viewBox="0 0 20 20"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden
        >
          <path
            d="M10 1L12 7.5L18.5 10L12 12.5L10 19L8 12.5L1.5 10L8 7.5L10 1Z"
            fill="#ffffff"
          />
        </svg>
      </div>
      {withText && (
        <span
          style={{
            fontSize: size * 0.54,
            fontWeight: 600,
            color: textColor,
            letterSpacing: -0.3,
          }}
        >
          {text}
        </span>
      )}
    </div>
  )
}
