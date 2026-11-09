import { WifiOff } from 'lucide-react'
import { Outlet } from 'react-router'
import { useConnection } from '../../api/connection'
import { useServerEvents } from '../../api/events'
import { serverEventsUrl } from '../../app/config'
import { OnboardingProvider } from '../onboarding/Onboarding'
import { Sidebar } from './Sidebar'
import styles from './AppShell.module.css'

export function AppShell() {
  useServerEvents(serverEventsUrl)
  const connection = useConnection()
  return (
    <OnboardingProvider>
      <div className={styles.shell}>
        <Sidebar />
        <main className={styles.main}>
          {connection === 'lost' && (
            <div className={styles.banner} role="status">
              <WifiOff size={16} aria-hidden />
              和做题龙的连接中断了，正在重连…请确认做题龙还开着，连上后页面会自动刷新。
            </div>
          )}
          <div className={styles.content}>
            <Outlet />
          </div>
        </main>
      </div>
    </OnboardingProvider>
  )
}
