import { useCallback, useState, type ImgHTMLAttributes } from 'react'
import { cx } from '../../lib/cx'
import styles from './LoadingImage.module.css'

/**
 * 题图、切图、解析图：还在下载时先占住一块浅色区域（与骨架屏同一种微光），
 * 下好后淡入，避免卡片先塌成一条再突然撑开。读不出来时的处理仍由调用方的 onError 负责。
 */
export function LoadingImage({
  className,
  onLoad,
  src,
  alt,
  ...props
}: ImgHTMLAttributes<HTMLImageElement> & { alt: string }) {
  const [loadedSrc, setLoadedSrc] = useState<string | undefined>(undefined)
  // 浏览器缓存里已经有的图，挂载时就是 complete，不会再触发 load
  const ref = useCallback(
    (img: HTMLImageElement | null) => {
      if (img?.complete && img.naturalWidth > 0) setLoadedSrc(src)
    },
    [src],
  )
  const loaded = loadedSrc === src
  return (
    <img
      ref={ref}
      {...props}
      src={src}
      alt={alt}
      className={cx(className, loaded ? styles.loaded : styles.pending)}
      aria-busy={loaded ? undefined : true}
      onLoad={(event) => {
        setLoadedSrc(src)
        onLoad?.(event)
      }}
    />
  )
}
