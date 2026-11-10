import { useState, type ClipboardEvent } from 'react'
import { endpoints, requestId } from '../../api/endpoints'
import { useAction } from '../../api/queries'
import { Button } from '../../components/ui/Button'
import { PhotoPicker, usePhotoUpload, type Photo } from './PhotoPicker'
import styles from './PracticeCard.module.css'
import { friendlyError } from '../../lib/errors'

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
  const [request, setRequest] = useState(requestId)
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

  const { add, uploading, error: uploadError } = usePhotoUpload(photos, setPhotos)
  const onPaste = (event: ClipboardEvent) => {
    const files = Array.from(event.clipboardData.files)
    if (files.length) {
      event.preventDefault()
      add(files)
    }
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

  const error = uploadError ?? (submit.error && friendlyError(submit.error))
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
      <PhotoPicker photos={photos} setPhotos={setPhotos} add={add} uploading={uploading} />
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
          disabled={submit.isPending || uploading || (!text.trim() && photos.length === 0)}
          onClick={send}
        >
          {submit.isPending ? '正在提交…' : attemptId ? '提交补充并批改' : '提交并批改'}
        </Button>
      </div>
    </div>
  )
}
