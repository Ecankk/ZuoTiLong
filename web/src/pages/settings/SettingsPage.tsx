import { usePreferences, useSavePreferences } from '../../api/queries'
import type { MathType } from '../../api/types'
import { AiServiceStatus } from '../../components/onboarding/AiServiceStatus'
import { useOpenOnboarding } from '../../components/onboarding/Onboarding'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Segmented } from '../../components/ui/Segmented'
import { DataCard } from './DataCard'
import { ModelCard } from './ModelCard'
import { ConventionCard, FreePracticeCard, MaskCard } from './PreferenceCards'
import styles from './SettingsPage.module.css'

function StudyType() {
  const { data: preferences } = usePreferences()
  const save = useSavePreferences()
  return (
    <Card padded className={styles.section} aria-label="备考类别">
      <h2>备考类别</h2>
      <p>做题龙按这里挑选练习，并默认遮挡同类别的真题，方便以后整卷自测。</p>
      {preferences && (
        <div className={styles.row}>
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
          {save.isPending && <span className={styles.note}>正在保存…</span>}
          {save.isSuccess && <span className={styles.saved}>已保存</span>}
        </div>
      )}
      {save.isError && <p className={styles.error}>{save.error.message}</p>}
    </Card>
  )
}

export function SettingsPage() {
  const openOnboarding = useOpenOnboarding()
  return (
    <>
      <PageHeader title="设置" />
      <div className={styles.stack}>
        <StudyType />
        <Card padded className={styles.section} aria-label="使用说明">
          <h2>使用说明</h2>
          <p>
            做题龙借助本机的 Codex 分析试卷、批改作答。上传试卷时请用黑笔作答、红笔批改；
            作答照片可以选择文件、拖入或粘贴。
          </p>
          <AiServiceStatus />
          <Button onClick={openOnboarding}>重新查看新手引导</Button>
        </Card>
        <ModelCard />
        <MaskCard />
        <FreePracticeCard />
        <ConventionCard />
        <DataCard />
        <Card padded className={styles.section} aria-label="关于">
          <h2>关于做题龙</h2>
          <p>版本信息和更新说明即将提供。</p>
        </Card>
      </div>
    </>
  )
}
