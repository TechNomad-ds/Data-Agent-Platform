import { useState, useEffect } from 'react'

/**
 * 订阅一个 CSS media query，返回是否匹配。
 * 使用同步的 matchMedia 初始化，避免首屏先渲染桌面态再切到移动态的闪烁。
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(
    () => typeof window !== 'undefined' && window.matchMedia(query).matches
  )

  useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = (e: MediaQueryListEvent) => setMatches(e.matches)
    // 订阅前同步一次，避免 query 变化时的短暂错位
    setMatches(mql.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])

  return matches
}

/** 移动端断点：视口宽度 ≤ 768px（含平板竖屏）。 */
export function useIsMobile(): boolean {
  return useMediaQuery('(max-width: 768px)')
}
