import { Image as ImageIcon, X } from 'lucide-react'
import { useState, type DragEvent } from 'react'
import { endpoints } from '../../api/endpoints'
import { useAction } from '../../api/queries'
import type { ImageRole, UploadedImage } from '../../api/types'
import { cx } from '../../lib/cx'
import styles from './PracticeCard.module.css'

const maxPhotos = 4
const maxBytes = 8 * 1024 * 1024

export type Photo = UploadedImage & { role: ImageRole }

/** 作答照片：选择、拖入或粘贴（粘贴由外层文本框转交 add），每张标注内容，选中后立即上传。 */
export function usePhotoUpload(
  photos: Photo[],
  setPhotos: (update: (before: Photo[]) => Photo[]) => void,
) {
  const [localError, setLocalError] = useState<string | null>(null)
  const upload = useAction((files: File[]) => endpoints.uploadImages(files), [])
  const add = (files: File[]) => {
    const images = files.filter((file) => file.type.startsWith('image/'))
    const room = maxPhotos - photos.length
    if (!images.length || room <= 0) return
    const tooBig = images.find((file) => file.size > maxBytes)
    if (tooBig) {
      upload.reset()
      setLocalError('每张照片不超过 8 MB')
      return
    }
    setLocalError(null)
    upload.mutate(images.slice(0, room), {
      onSuccess: (result) =>
        setPhotos((before) => [
          ...before,
          ...result.images.map((image) => ({ ...image, role: 'own_work' as const })),
        ]),
    })
  }
  return { add, uploading: upload.isPending, error: localError ?? upload.error?.message ?? null }
}

export function PhotoPicker({
  photos,
  setPhotos,
  add,
  uploading,
}: {
  photos: Photo[]
  setPhotos: (update: (before: Photo[]) => Photo[]) => void
  add: (files: File[]) => void
  uploading: boolean
}) {
  const [dragging, setDragging] = useState(false)
  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    add(Array.from(event.dataTransfer.files))
  }
  return (
    <>
      <div className={styles.photos}>
        {photos.map((photo, index) => (
          <figure key={photo.id} className={styles.thumb} style={{ margin: 0 }}>
            <img src={photo.url} alt={`作答照片 ${index + 1}`} />
            <button
              type="button"
              className={styles.remove}
              title="移除"
              onClick={() => setPhotos((before) => before.filter((p) => p.id !== photo.id))}
            >
              <X size={12} aria-hidden />
            </button>
            <select
              aria-label={`第 ${index + 1} 张照片的内容`}
              value={photo.role}
              onChange={(event) =>
                setPhotos((before) =>
                  before.map((p) =>
                    p.id === photo.id ? { ...p, role: event.target.value as ImageRole } : p,
                  ),
                )
              }
            >
              <option value="own_work">我的作答</option>
              <option value="marking">事后批改</option>
              <option value="external_solution">参考解析</option>
            </select>
          </figure>
        ))}
        {photos.length < maxPhotos && (
          <label
            className={cx(styles.drop, dragging && styles.dragging)}
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <ImageIcon size={20} aria-hidden />
            <span>{uploading ? '正在上传…' : '选择照片'}</span>
            <span className={styles.faint}>或拖入、粘贴到这里</span>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              disabled={uploading}
              onChange={(event) => {
                add(Array.from(event.target.files ?? []))
                event.target.value = ''
              }}
            />
          </label>
        )}
      </div>
      <p className={styles.note}>
        最多 4 张，每张不超过 8 MB，可以只传照片不写文字。截图后直接 Ctrl+V 也能添加。
      </p>
    </>
  )
}
