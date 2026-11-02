import { Eye, EyeOff, Image as ImageIcon, X } from 'lucide-react'
import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent } from 'react'
import type { PracticeResponse } from '../../api/types'
import { MathText } from '../../components/math/MathText'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { cx } from '../../lib/cx'
import { mathTypeName, sourceName } from '../../lib/labels'
import styles from './PracticeCard.module.css'

type Photo = { id: string; url: string; role: 'own_work' | 'marking' | 'external_solution' }

const maxPhotos = 4
const writesReady = false

/** 作答照片：选择文件、拖入或粘贴；当前只在本地预览，提交接口接入后上传。 */
function usePhotos() {
  const [photos, setPhotos] = useState<Photo[]>([])
  const urls = useRef(new Set<string>())
  useEffect(() => {
    const current = urls.current
    return () => current.forEach((url) => URL.revokeObjectURL(url))
  }, [])
  const add = (files: File[]) => {
    const images = files.filter((file) => file.type.startsWith('image/'))
    setPhotos((before) => [
      ...before,
      ...images.slice(0, maxPhotos - before.length).map((file) => {
        const url = URL.createObjectURL(file)
        urls.current.add(url)
        return { id: url, url, role: 'own_work' as const }
      }),
    ])
  }
  const remove = (id: string) => {
    URL.revokeObjectURL(id)
    urls.current.delete(id)
    setPhotos((before) => before.filter((photo) => photo.id !== id))
  }
  const setRole = (id: string, role: Photo['role']) =>
    setPhotos((before) => before.map((photo) => (photo.id === id ? { ...photo, role } : photo)))
  return { photos, add, remove, setRole }
}

function MaskedQuestion({ mathType }: { mathType: string }) {
  return (
    <div className={styles.masked}>
      <EyeOff size={22} aria-hidden />
      <strong>{mathType}真题，默认遮挡</strong>
      <p>你在备考{mathType}，同类别真题可能留作整卷自测。查看后会记为“看过题目”。</p>
      <Button variant="soft" disabled={!writesReady} title="查看题目即将开放">
        <Eye size={16} aria-hidden />
        查看题目
      </Button>
    </div>
  )
}

export function AnswerCard({
  detail,
  position,
  topicName,
}: {
  detail: PracticeResponse
  position: { index: number; total: number }
  topicName: string
}) {
  const { practice } = detail
  const [text, setText] = useState('')
  const [dragging, setDragging] = useState(false)
  const { photos, add, remove, setRole } = usePhotos()
  const questionText = detail.question?.question_text
  // 提交作答、上传照片和确认查看题目在下一批接入，先禁用
  const canSubmit = writesReady && detail.actions.includes('submit')

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

  return (
    <Card className={styles.card} aria-label="当前练习">
      <div className={styles.split}>
        <div>
          <p className={styles.eyebrow}>
            {topicName} · 第 {position.index} / {position.total} 道
          </p>
          <h2>
            {sourceName(practice.access)} · 第 {practice.access.number} 题
          </h2>
          {detail.selection_reason && (
            <p className={styles.why}>
              <b>为什么练这道：</b>
              <MathText text={detail.selection_reason} />
            </p>
          )}
          {questionText ? (
            <div className={cx('read', styles.question)}>
              <MathText text={questionText} />
            </div>
          ) : (
            detail.actions.includes('reveal_question') && (
              <MaskedQuestion mathType={mathTypeName(practice.access.math_type)} />
            )
          )}
        </div>

        <div className={styles.answer}>
          <label className={styles.label} htmlFor={`answer-${practice.id}`}>
            你的作答
          </label>
          <textarea
            id={`answer-${practice.id}`}
            className={styles.textarea}
            placeholder="写下关键步骤即可；也可以直接上传手写照片，不用把整页誊一遍。"
            value={text}
            onChange={(event) => setText(event.target.value)}
            onPaste={onPaste}
            disabled={!canSubmit}
          />
          <div className={styles.photos}>
            {photos.map((photo, index) => (
              <figure key={photo.id} className={styles.thumb} style={{ margin: 0 }}>
                <img src={photo.url} alt={`作答照片 ${index + 1}`} />
                <button
                  type="button"
                  className={styles.remove}
                  title="移除"
                  onClick={() => remove(photo.id)}
                >
                  <X size={12} aria-hidden />
                </button>
                <select
                  aria-label={`第 ${index + 1} 张照片的内容`}
                  value={photo.role}
                  onChange={(event) => setRole(photo.id, event.target.value as Photo['role'])}
                >
                  <option value="own_work">我的作答</option>
                  <option value="marking">事后批改</option>
                  <option value="external_solution">参考解析</option>
                </select>
              </figure>
            ))}
            {photos.length < maxPhotos && canSubmit && (
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
                <span>选择照片</span>
                <span className={styles.faint}>或拖入、粘贴到这里</span>
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  multiple
                  onChange={(event) => {
                    add(Array.from(event.target.files ?? []))
                    event.target.value = ''
                  }}
                />
              </label>
            )}
          </div>
          <p className={styles.note}>
            {writesReady
              ? '最多 4 张，可以只传照片不写文字。截图后直接 Ctrl+V 也能添加。'
              : '提交作答和上传照片即将开放，现在可以先看题、在纸上作答。'}
          </p>
          <div className={styles.submitRow}>
            <label className={styles.check}>
              <input type="checkbox" disabled={!canSubmit} />
              做之前看过这道题的答案或解析
            </label>
            <span className={styles.submitHint}>一般 1～2 分钟出批改结果</span>
            <Button
              variant="primary"
              size="lg"
              disabled={!canSubmit || (!text.trim() && photos.length === 0)}
            >
              提交并批改
            </Button>
          </div>
        </div>
      </div>
    </Card>
  )
}
