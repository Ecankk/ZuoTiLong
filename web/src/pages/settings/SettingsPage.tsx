import { useQuery } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router'
import { request } from '../../api/client'
import { usePreferences, useSavePreferences } from '../../api/queries'
import type { MathType } from '../../api/types'
import { AiServiceStatus } from '../../components/onboarding/AiServiceStatus'
import { useOpenOnboarding } from '../../components/onboarding/Onboarding'
import { Button } from '../../components/ui/Button'
import { ButtonRow } from '../../components/ui/ButtonRow'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Segmented } from '../../components/ui/Segmented'
import { friendlyError } from '../../lib/errors'
import { SETUP_GUIDE_PATH } from '../../lib/setup'
import { CollectionImportCard } from './CollectionImportCard'
import { DataCard, DataPaths } from './DataCard'
import { ModelSettings } from './ModelCard'
import { ConventionCard, ConventionRaw, FreePracticeCard, MaskCard } from './PreferenceCards'
import styles from './SettingsPage.module.css'

/** 左侧目录：页面较宽时显示，点一下跳到对应的卡片 */
const sections = [
  { id: 'settings-study', label: '备考类别' },
  { id: 'settings-guide', label: '使用说明' },
  { id: 'settings-practice', label: '练习偏好' },
  { id: 'settings-convention', label: '笔迹约定' },
  { id: 'settings-import', label: '导入题集' },
  { id: 'settings-data', label: '数据与备份' },
  { id: 'settings-advanced', label: '高级设置' },
  { id: 'settings-about', label: '关于' },
]

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
      {save.isError && <p className={styles.error}>{friendlyError(save.error)}</p>}
    </Card>
  )
}

/** 高级设置：模型、约定原文、数据位置。默认收起，普通使用不需要打开。 */
function Advanced() {
  return (
    <Card padded className={styles.section} aria-label="高级设置">
      <details className={styles.advanced}>
        <summary>
          <ChevronRight size={18} className={styles.chevron} aria-hidden />
          <span>
            <strong>高级设置</strong>
            <small>AI 模型、笔迹约定原文、数据文件位置。一般不需要修改。</small>
          </span>
        </summary>
        <div className={styles.advancedBody}>
          <ModelSettings />
          <ConventionRaw />
          <DataPaths />
        </div>
      </details>
    </Card>
  )
}

/** 关于：版本号来自 GET /api/health */
function About() {
  const { data } = useQuery({
    queryKey: ['health'],
    queryFn: () => request<{ version?: string }>('/api/health'),
    staleTime: Infinity,
  })
  return (
    <Card padded className={styles.section} aria-label="关于">
      <h2>关于做题龙</h2>
      <p>做题龙帮你分析做过的试卷，找出薄弱考点，再挑题针对练习。所有数据只保存在这台电脑上。</p>
      <dl className={styles.facts}>
        <dt>版本</dt>
        <dd>{data?.version ? `v${data.version}` : '读取中…'}</dd>
      </dl>
    </Card>
  )
}

function Anchors() {
  return (
    <nav className={styles.anchors} aria-label="设置目录">
      {sections.map((section) => (
        <a
          key={section.id}
          href={`#${section.id}`}
          onClick={(event) => {
            event.preventDefault()
            document
              .getElementById(section.id)
              ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }}
        >
          {section.label}
        </a>
      ))}
    </nav>
  )
}

export function SettingsPage() {
  const openOnboarding = useOpenOnboarding()
  return (
    <>
      <PageHeader title="设置" />
      <div className={styles.layout}>
        <Anchors />
        <div className={styles.stack}>
          <div id="settings-study" className={styles.anchor}>
            <StudyType />
          </div>
          <div id="settings-guide" className={styles.anchor}>
            <Card padded className={styles.section} aria-label="使用说明">
              <h2>使用说明</h2>
              <p>
                做题龙借助这台电脑上的 AI
                服务（Codex）分析试卷、批改作答。上传试卷时请按“笔迹约定”书写；作答照片可以选择文件、拖入或粘贴。
              </p>
              <AiServiceStatus showGuideLink={false} />
              <ButtonRow className={styles.row}>
                <Button onClick={openOnboarding}>重新查看新手引导</Button>
                <Link className={styles.textLink} to={SETUP_GUIDE_PATH}>
                  查看配置教程
                </Link>
              </ButtonRow>
            </Card>
          </div>
          <div id="settings-practice" className={styles.anchorGroup}>
            <MaskCard />
            <FreePracticeCard />
          </div>
          <div id="settings-convention" className={styles.anchor}>
            <ConventionCard />
          </div>
          <div id="settings-import" className={styles.anchor}>
            <CollectionImportCard />
          </div>
          <div id="settings-data" className={styles.anchor}>
            <DataCard />
          </div>
          <div id="settings-advanced" className={styles.anchor}>
            <Advanced />
          </div>
          <div id="settings-about" className={styles.anchor}>
            <About />
          </div>
        </div>
      </div>
    </>
  )
}
