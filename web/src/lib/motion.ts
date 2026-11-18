/** 用户在系统里开了“减少动画”时返回 true；没有 matchMedia 的环境（测试）视为没开。 */
export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false
}

/** JS 触发的滚动（scrollIntoView / scrollTo）用的 behavior：减少动画时直接跳到位。 */
export function scrollBehavior(): ScrollBehavior {
  return prefersReducedMotion() ? 'auto' : 'smooth'
}
