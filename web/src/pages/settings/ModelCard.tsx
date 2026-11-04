import { CircleAlert, LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import { useAgentModels, usePreferences, useSavePreferences } from '../../api/queries'
import type { AgentModels, ExecutionProfile, Preferences, ProfileTier } from '../../api/types'
import onboarding from '../../components/onboarding/Onboarding.module.css'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { closestEffort } from '../../lib/models'
import styles from './SettingsPage.module.css'

type Model = AgentModels['items'][number]

const tiers: { tier: ProfileTier; name: string; usage: string }[] = [
  { tier: 'judgment', name: '判断', usage: '分析试卷、单题复核、批改作答' },
  { tier: 'organization', name: '整理', usage: '选择练习、整理考点、总结' },
]

type Draft = Partial<Record<ProfileTier, ExecutionProfile & { adjusted?: string }>>

const same = (a: ExecutionProfile, b: ExecutionProfile) =>
  a.model === b.model && a.effort === b.effort

function ProfileRow({
  name,
  usage,
  value,
  adjusted,
  models,
  ready,
  onChange,
}: {
  name: string
  usage: string
  value: ExecutionProfile
  adjusted?: string
  models: Model[]
  ready: boolean
  onChange: (value: ExecutionProfile, adjusted?: string) => void
}) {
  const model = models.find((item) => item.id === value.model)
  const efforts = model?.efforts ?? []
  const missing = ready && (!model || !efforts.includes(value.effort))

  const pickModel = (id: string) => {
    const next = models.find((item) => item.id === id)
    if (!next) return
    if (next.efforts.includes(value.effort)) return onChange({ model: id, effort: value.effort })
    const effort = closestEffort(value.effort, next.efforts)
    onChange({ model: id, effort }, `${next.name} 不支持“${value.effort}”，已改为“${effort}”。`)
  }

  return (
    <div className={styles.profile}>
      <div className={styles.profileHead}>
        <strong>{name}</strong>
        <span className={styles.note}>用于{usage}</span>
      </div>
      <div className={styles.profileFields}>
        <select
          className={styles.select}
          aria-label={`${name}用的模型`}
          disabled={!ready}
          value={value.model}
          onChange={(event) => pickModel(event.target.value)}
        >
          {!model && <option value={value.model}>{value.model}</option>}
          {models.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <select
          className={styles.select}
          aria-label={`${name}的推理强度`}
          disabled={!ready}
          value={value.effort}
          onChange={(event) => onChange({ model: value.model, effort: event.target.value })}
        >
          {!efforts.includes(value.effort) && <option value={value.effort}>{value.effort}</option>}
          {efforts.map((effort) => (
            <option key={effort} value={effort}>
              {effort}
            </option>
          ))}
        </select>
      </div>
      {missing && (
        <p className={styles.rowWarn} role="alert">
          <CircleAlert size={14} aria-hidden /> 本机不可用，任务会失败。请换成列表里的模型。
        </p>
      )}
      {!missing && adjusted && <p className={styles.rowNote}>{adjusted}</p>}
    </div>
  )
}

function ModelStatus({ models }: { models: AgentModels | undefined }) {
  if (!models || models.status === 'checking')
    return (
      <div className={onboarding.status} role="status">
        <LoaderCircle size={22} color="var(--color-primary)" aria-hidden />
        <div>
          <strong>正在读取本机可用的模型</strong>
          <small>读取完成前不能修改，稍等片刻会自动刷新。</small>
        </div>
      </div>
    )
  if (models.status === 'available') return null
  const { reason } = models
  const setup = reason === 'not_installed' || reason === 'not_logged_in'
  return (
    <div className={onboarding.status} role="status">
      <CircleAlert size={22} color="var(--status-partial)" aria-hidden />
      <div>
        <strong>
          {reason === 'not_installed'
            ? '本机还没有安装 Codex，暂时不能选择模型'
            : reason === 'not_logged_in'
              ? 'Codex 还没有登录，暂时不能选择模型'
              : '暂时读不到本机可用的模型'}
        </strong>
        <small>
          {setup
            ? '按上面“使用说明”里的步骤准备好 Codex，这里会自动刷新。'
            : models.message || '稍后再打开这个页面试试。'}
        </small>
      </div>
    </div>
  )
}

function ModelForm({ preferences, models }: { preferences: Preferences; models?: AgentModels }) {
  const saved = preferences.execution_profiles
  const [draft, setDraft] = useState<Draft>({})
  const [message, setMessage] = useState('')
  const save = useSavePreferences()
  const ready = models?.status === 'available'
  const changes = Object.fromEntries(
    tiers
      .map(({ tier }) => [tier, draft[tier]] as const)
      .filter(([tier, value]) => value && !same(value, saved[tier]))
      .map(([tier, value]) => [tier, { model: value!.model, effort: value!.effort }]),
  )
  const dirty = Object.keys(changes).length > 0

  const submit = (body: Parameters<typeof save.mutate>[0], done: string) => {
    setMessage('')
    save.mutate(body, {
      onSuccess: () => {
        setDraft({})
        setMessage(done)
      },
    })
  }

  return (
    <>
      {tiers.map(({ tier, name, usage }) => (
        <ProfileRow
          key={tier}
          name={name}
          usage={usage}
          value={draft[tier] ?? saved[tier]}
          adjusted={draft[tier]?.adjusted}
          models={models?.items ?? []}
          ready={ready}
          onChange={(value, adjusted) => {
            setMessage('')
            setDraft((current) => ({ ...current, [tier]: { ...value, adjusted } }))
          }}
        />
      ))}
      <div className={styles.row}>
        <Button
          variant="primary"
          disabled={!ready || !dirty || save.isPending}
          onClick={() => submit({ execution_profiles: changes }, '已保存，下一个任务起生效')}
        >
          保存
        </Button>
        <Button
          disabled={save.isPending}
          onClick={() => submit({ execution_profiles: null }, '已恢复默认，下一个任务起生效')}
        >
          恢复默认
        </Button>
        {save.isPending && <span className={styles.note}>正在保存…</span>}
        {message && !dirty && (
          <span className={styles.saved} role="status">
            {message}
          </span>
        )}
      </div>
      {save.error && <p className={styles.error}>{save.error.message}</p>}
    </>
  )
}

/** AI 模型：判断类和整理类任务各用哪个模型、思考多深。保存后不会启动任何任务。 */
export function ModelCard() {
  const { data: preferences } = usePreferences()
  const { data: models } = useAgentModels()
  return (
    <Card padded className={styles.section} aria-label="AI 模型">
      <h2>AI 模型</h2>
      <p>
        做题龙把工作分成两类：需要仔细判断的，和整理归纳的。可以分别选择 Codex
        用的模型和推理强度（reasoning effort，常见 low / medium / high /
        xhigh），越高越仔细，也越慢。
      </p>
      <ModelStatus models={models} />
      {preferences && <ModelForm preferences={preferences} models={models} />}
    </Card>
  )
}
