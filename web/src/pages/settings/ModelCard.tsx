import { CircleAlert, LoaderCircle, Search } from 'lucide-react'
import { useState } from 'react'
import { useAgentModels, usePreferences, useSavePreferences } from '../../api/queries'
import type { AgentModels, ExecutionProfile, Preferences, ProfileTier } from '../../api/types'
import onboarding from '../../components/onboarding/Onboarding.module.css'
import { Button } from '../../components/ui/Button'
import { friendlyError } from '../../lib/errors'
import { closestEffort } from '../../lib/models'
import { effortLabel, filterModels, groupModels, searchThreshold, type Model } from './modelOptions'
import styles from './SettingsPage.module.css'

const tiers: { tier: ProfileTier; name: string; short: string; usage: string }[] = [
  {
    tier: 'judgment',
    name: '需要仔细判断的工作',
    short: '判断类任务',
    usage: '分析试卷、复核单题、批改作答',
  },
  {
    tier: 'organization',
    name: '整理归纳的工作',
    short: '整理类任务',
    usage: '挑选练习、整理考点、写总结',
  },
]

type Draft = Partial<Record<ProfileTier, ExecutionProfile & { adjusted?: string }>>

const same = (a: ExecutionProfile, b: ExecutionProfile) =>
  a.model === b.model && a.effort === b.effort

/** 模型下拉：模型多时可以搜索，多个系列时按名称前缀分组 */
function ModelSelect({
  label,
  value,
  models,
  ready,
  onPick,
}: {
  label: string
  value: string
  models: Model[]
  ready: boolean
  onPick: (id: string) => void
}) {
  const [query, setQuery] = useState('')
  const current = models.find((item) => item.id === value)
  const matched = filterModels(models, query)
  // 搜索时也保留当前选中的模型，下拉框才不会显示错位
  const shown = current && !matched.includes(current) ? [current, ...matched] : matched
  const groups = groupModels(shown)
  const options = (items: Model[]) =>
    items.map((item) => (
      <option key={item.id} value={item.id}>
        {item.name}
      </option>
    ))
  return (
    <div className={styles.modelPicker}>
      {ready && models.length > searchThreshold && (
        <label className={styles.modelSearch}>
          <Search size={14} aria-hidden />
          <input
            type="search"
            aria-label={`搜索${label}`}
            placeholder={`在 ${models.length} 个模型里搜索`}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      )}
      <select
        className={styles.select}
        aria-label={label}
        disabled={!ready}
        value={value}
        onChange={(event) => onPick(event.target.value)}
      >
        {!current && <option value={value}>{value || '未选择'}</option>}
        {groups.length === 1
          ? options(groups[0].models)
          : groups.map((group) => (
              <optgroup key={group.family} label={group.family}>
                {options(group.models)}
              </optgroup>
            ))}
      </select>
      {ready && query && matched.length === 0 && (
        <span className={styles.note}>没有名称包含“{query}”的模型</span>
      )}
    </div>
  )
}

function ProfileRow({
  name,
  short,
  usage,
  value,
  adjusted,
  models,
  ready,
  onChange,
}: {
  name: string
  short: string
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
    onChange(
      { model: id, effort },
      `${next.name} 没有“${effortLabel(value.effort, efforts)}”这一档，已改为“${effortLabel(effort, next.efforts)}”。`,
    )
  }

  return (
    <div className={styles.profile}>
      <div className={styles.profileHead}>
        <strong>{name}</strong>
        <span className={styles.note}>{usage}</span>
      </div>
      <div className={styles.profileFields}>
        <div className={styles.field}>
          <span>模型</span>
          <ModelSelect
            label={`${short}用的模型`}
            value={value.model}
            models={models}
            ready={ready}
            onPick={pickModel}
          />
        </div>
        <div className={styles.field}>
          <span>思考深度</span>
          <select
            className={styles.select}
            aria-label={`${short}的思考深度`}
            disabled={!ready}
            value={value.effort}
            onChange={(event) => onChange({ model: value.model, effort: event.target.value })}
          >
            {!efforts.includes(value.effort) && (
              <option value={value.effort}>{effortLabel(value.effort)}</option>
            )}
            {efforts.map((effort) => (
              <option key={effort} value={effort}>
                {effortLabel(effort, efforts)}
              </option>
            ))}
          </select>
        </div>
      </div>
      {missing && (
        <p className={styles.rowWarn} role="alert">
          <CircleAlert size={14} aria-hidden />{' '}
          这台电脑上用不了这个模型，相关任务会失败。请换成列表里的模型。
        </p>
      )}
      {!missing && adjusted && <p className={styles.rowNote}>{adjusted}</p>}
    </div>
  )
}

/** 模型列表读不到时的说明；不显示后端原始文字 */
function ModelStatus({ models }: { models: AgentModels | undefined }) {
  if (!models || models.status === 'checking')
    return (
      <div className={onboarding.status} role="status">
        <LoaderCircle size={22} color="var(--color-primary)" aria-hidden />
        <div>
          <strong>正在读取这台电脑上可用的模型</strong>
          <small>读取完成前不能修改，稍等片刻会自动刷新。</small>
        </div>
      </div>
    )
  if (models.status === 'available' && models.items.length > 0) return null
  const { reason } = models
  const title =
    models.status === 'available'
      ? '这台电脑上暂时没有可选的模型'
      : reason === 'not_installed'
        ? 'AI 服务还没有安装，暂时不能选择模型'
        : reason === 'not_logged_in'
          ? 'AI 服务还没有登录，暂时不能选择模型'
          : reason === 'disabled'
            ? 'AI 服务现在没有启用，暂时不能选择模型'
            : '暂时读不到可用的模型'
  const hint =
    reason === 'not_installed' || reason === 'not_logged_in'
      ? '按“使用说明”里的步骤准备好 AI 服务，这里会自动刷新。'
      : '现在会继续使用下面保存的设置。稍后再打开这个页面试试。'
  return (
    <div className={onboarding.status} role="status">
      <CircleAlert size={22} color="var(--status-partial)" aria-hidden />
      <div>
        <strong>{title}</strong>
        <small>{hint}</small>
      </div>
    </div>
  )
}

function ModelForm({ preferences, models }: { preferences: Preferences; models?: AgentModels }) {
  const saved = preferences.execution_profiles
  const [draft, setDraft] = useState<Draft>({})
  const [message, setMessage] = useState('')
  const save = useSavePreferences()
  const ready = models?.status === 'available' && models.items.length > 0
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
      {tiers.map(({ tier, name, short, usage }) => (
        <ProfileRow
          key={tier}
          name={name}
          short={short}
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
      {save.error && <p className={styles.error}>{friendlyError(save.error)}</p>}
    </>
  )
}

/**
 * 高级设置里的“AI 模型与思考深度”：判断类和整理类任务各用哪个模型、想多深。
 * 保存后不会启动任何任务。
 */
export function ModelSettings() {
  const { data: preferences } = usePreferences()
  const { data: models } = useAgentModels()
  return (
    <section className={styles.subsection} aria-label="AI 模型与思考深度">
      <h3>AI 模型与思考深度</h3>
      <p>
        做题龙的工作分两类：需要仔细判断的，和整理归纳的。可以分别选模型和思考深度——想得越深越仔细，也越慢。一般保持默认就好。
      </p>
      <ModelStatus models={models} />
      {preferences && <ModelForm preferences={preferences} models={models} />}
    </section>
  )
}
