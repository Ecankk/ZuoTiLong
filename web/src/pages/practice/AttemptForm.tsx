import { Image as ImageIcon, X } from 'lucide-react'
import { useState, type ClipboardEvent, type DragEvent } from 'react'
import { endpoints, requestId } from '../../api/endpoints'
import { useAction } from '../../api/queries'
import type { ImageRole, UploadedImage } from '../../api/types'
import { Button } from '../../components/ui/Button'
import { cx } from '../../lib/cx'
import styles from './PracticeCard.module.css'

const maxPhotos = 4
const maxBytes = 8 * 1024 * 1024

type Photo = UploadedImage & { role: ImageRole }

/**
 * 作答表单：文字加手写照片（选择、拖入或粘贴，每张标注内容）。
 * 照片选中后立即上传保存，提交时只发送照片编号。
 */
export function AttemptForm({
  practiceId,
  attemptId,
  showExposure,
  onSubmitted,
}: {
  practiceId: string
  /** 有值时为补充作答 */
  attemptId?: string
  showExposure: boolean
  /** 提交成功后（如收起补充表单） */
  onSubmitted?: () => void
}) {
  const [text, setText] = useState('')
  const [photos, setPhotos] = useState<Photo[]>([])
  const [exposed, setExposed] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [request, setRequest] = useState(requestId)
  const [localError, setLocalError] = useState<string | null>(null)
  const upload = useAction((files: File[]) => endpoints.uploadImages(files), [])
  const submit = useAction(() => {
    const body = {
      response: text.trim(),
      image_ids: photos.map((photo) => photo.id),
      image_roles: Object.fromEntries(photos.map((photo) => [photo.id, photo.role])),
      answer_exposed: exposed,
      request_id: request,
    }
    return attemptId
      ? endpoints.supplementAttempt(attemptId, body)
      : endpoints.submitAttempt(practiceId, body)
  }, [['practices'], ['tasks']])

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
  const onPaste = (event: ClipboardEvent) => {
    const files = Array.from(event.clipboardData.files)
    if (files.length) {
      event.preventDefault()
      add(files)
    }
  }
  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    add(Array.from(event.dataTransfer.files))
  }
  const send = () =>
    submit.mutate(undefined, {
      onSuccess: () => {
        setText('')
        setPhotos([])
        setExposed(false)
        setRequest(requestId())
        onSubmitted?.()
      },
    })

  const error = localError ?? upload.error?.message ?? submit.error?.message
  return (
    <div className={styles.answer}>
      <label className={styles.label} htmlFor={`answer-${practiceId}`}>
        {attemptId ? '补充步骤或照片' : '你的作答'}
      </label>
      <textarea
        id={`answer-${practiceId}`}
        className={styles.textarea}
        placeholder={
          attemptId
            ? '补上缺少的步骤，或重拍看不清的地方。'
            : '写下关键步骤即可；也可以直接上传手写照片，不用把整页誊一遍。'
        }
        maxLength={16000}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onPaste={onPaste}
      />
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
            <span>{upload.isPending ? '正在上传…' : '选择照片'}</span>
            <span className={styles.faint}>或拖入、粘贴到这里</span>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              disabled={upload.isPending}
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
      {error && <p className={styles.formError}>{error}</p>}
      <div className={styles.submitRow}>
        {showExposure && (
          <label className={styles.check}>
            <input
              type="checkbox"
              checked={exposed}
              onChange={(event) => setExposed(event.target.checked)}
            />
            做之前看过这道题的答案或解析
          </label>
        )}
        <span className={styles.submitHint}>
          {submit.isSuccess ? '已提交，做题龙会尽快批改' : '提交后由做题龙批改'}
        </span>
        <Button
          variant="primary"
          size="lg"
          disabled={submit.isPending || upload.isPending || (!text.trim() && photos.length === 0)}
          onClick={send}
        >
          {submit.isPending ? '正在提交…' : attemptId ? '提交补充并批改' : '提交并批改'}
        </Button>
      </div>
    </div>
  )
}
