import * as Dialog from '@radix-ui/react-dialog'
import { createContext, useContext, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { usePapers, usePreferences, useSavePreferences } from '../../api/queries'
import type { MathType } from '../../api/types'
import { clientStateKeys, useClientState } from '../../lib/clientState'
import { cx } from '../../lib/cx'
import { friendlyError } from '../../lib/errors'
import { Button } from '../ui/Button'
import { Segmented } from '../ui/Segmented'
import { AiServiceStatus } from './AiServiceStatus'
import styles from './Onboarding.module.css'

const OnboardingContext = createContext<() => void>(() => {})

/** 设置页“使用说明”用它重新打开引导。 */
export const useOpenOnboarding = () => useContext(OnboardingContext)

function StudyTypeStep() {
  const { data: preferences } = usePreferences()
  const save = useSavePreferences()
  if (!preferences) return null
  return (
    <>
      <p>做题龙会按你的备考类别挑选练习，并默认遮挡同类别的真题，方便以后整卷自测。</p>
      <div className={styles.choices}>
        <Segmented<string>
          label="备考类别"
          items={[
            { value: '1', label: '数学一' },
            { value: '2', label: '数学二' },
            { value: '3', label: '数学三' },
          ]}
          value={String(preferences.study_type)}
          onChange={(value) => save.mutate({ study_type: Number(value) as MathType })}
        />
        {save.isSuccess && <span className={styles.saved}>已保存</span>}
      </div>
      {save.isError && <p className={styles.error}>{friendlyError(save.error)}</p>}
    </>
  )
}

const flow = ['上传做过的试卷', '逐题分析', '针对薄弱考点练习', '拍照提交作答', '批改与画像']

type Step = { title: string; body: (ctx: { close: () => void; hasPapers: boolean }) => ReactNode }

const steps: Step[] = [
  {
    title: '做题龙能做什么',
    body: () => (
      <>
        <p>把做过的试卷交给做题龙，它会找出每道题错在哪，再针对薄弱考点挑几道真题让你练。</p>
        <ol className={styles.flow}>
          {flow.map((item, index) => (
            <li key={item}>
              <b>{index + 1}</b>
              {item}
            </li>
          ))}
        </ol>
      </>
    ),
  },
  {
    title: '准备 AI 服务',
    body: ({ close }) => (
      <>
        <p>做题龙使用 Codex 分析试卷和批改作答，需要一个可用的 ChatGPT 账号（如 Plus）。</p>
        <AiServiceStatus onGuide={close} />
        <p>也可以先跳过，之后首页和左下角会继续提醒。</p>
      </>
    ),
  },
  { title: '选择备考类别', body: () => <StudyTypeStep /> },
  {
    title: '笔迹约定',
    body: () => (
      <>
        <p>上传试卷前，请按这个约定书写，做题龙才能分清哪些是考场作答：</p>
        <div className={styles.pens}>
          <span className={styles.pen}>
            <i style={{ background: 'var(--text-strong)' }} />
            黑笔：考试时的作答，包括考场上的自查改写
          </span>
          <span className={styles.pen}>
            <i style={{ background: 'var(--status-wrong)' }} />
            红笔：考后的批改和订正
          </span>
        </div>
        <p>用别的颜色的笔也可以，到“设置 → 笔迹约定”里改一下。</p>
        <p>做练习时，作答照片可以选择文件、直接拖进来，或截图后粘贴。</p>
      </>
    ),
  },
  {
    title: '开始吧',
    body: ({ hasPapers }) =>
      hasPapers ? (
        <p>
          你已经有分析过的试卷了。去“练习”看看为薄弱考点准备的题，或者在“试卷”里继续上传新的试卷。
        </p>
      ) : (
        <p>上传第一份做过的试卷 PDF。分析完成后，逐题结果和练习会出现在“试卷”和“练习”里。</p>
      ),
  },
]

/**
 * “已看过引导”存在后端草稿里（桌面版每次启动 origin 都变，浏览器存储留不住）。
 * 读到之前不弹出；读取失败时也不弹，免得每次打开都被打扰（设置页可以重新打开）。
 */
export function OnboardingProvider({ children }: { children: ReactNode }) {
  const seen = useClientState<boolean>(clientStateKeys.onboardingSeen, {
    fallback: false,
    fromLegacy: (raw) => (raw === '1' ? true : undefined),
  })
  const [manual, setManual] = useState<boolean | null>(null)
  const open = manual ?? (seen.ready && !seen.failed && !seen.value)
  const setOpen = (next: boolean) => setManual(next)
  const [step, setStep] = useState(0)
  const contentRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  // 第 5 步按有没有试卷给不同的下一步；只在引导打开时读取
  const { data: papers } = usePapers('0')
  const hasPapers = (papers?.items.length ?? 0) > 0
  const close = () => {
    if (!seen.value) seen.set(true)
    setOpen(false)
  }
  const reopen = () => {
    setStep(0)
    setOpen(true)
  }
  const last = step === steps.length - 1
  return (
    <OnboardingContext.Provider value={reopen}>
      {children}
      <Dialog.Root open={open} onOpenChange={(next) => (next ? setOpen(true) : close())}>
        <Dialog.Portal>
          <Dialog.Overlay className={styles.overlay} />
          <Dialog.Content
            ref={contentRef}
            className={styles.dialog}
            aria-describedby={undefined}
            onOpenAutoFocus={(event) => {
              // 焦点放在弹窗本身：默认会落到“跳过引导”上，按回车就直接跳过了
              event.preventDefault()
              contentRef.current?.focus()
            }}
          >
            <div className={styles.top}>
              <img src="/brand/logo-icon.png" alt="" />
              <span className={styles.stepLabel}>
                第 {step + 1} 步，共 {steps.length} 步
              </span>
              <span className={styles.progress} aria-hidden>
                {steps.map((item, index) => (
                  <i key={item.title} className={cx(index <= step && styles.done)} />
                ))}
              </span>
            </div>
            {/* key 按步骤：换步时正文重新挂载，播放淡入 */}
            <Dialog.Title key={`title-${step}`} className={styles.stepTitle}>
              {steps[step].title}
            </Dialog.Title>
            <div key={`body-${step}`} className={styles.body}>
              {steps[step].body({ close, hasPapers })}
            </div>
            <div className={styles.footer}>
              <Button variant="ghost" className={styles.skip} onClick={close}>
                跳过引导
              </Button>
              {step > 0 && <Button onClick={() => setStep(step - 1)}>上一步</Button>}
              {last ? (
                <Button
                  variant="primary"
                  onClick={() => {
                    close()
                    navigate(hasPapers ? '/practice' : '/papers')
                  }}
                >
                  {hasPapers ? '去看看练习' : '去上传试卷'}
                </Button>
              ) : (
                <Button variant="primary" onClick={() => setStep(step + 1)}>
                  下一步
                </Button>
              )}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </OnboardingContext.Provider>
  )
}
