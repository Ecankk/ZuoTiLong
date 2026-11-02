import { Outlet } from 'react-router'
import { useServerEvents } from '../../api/events'
import { serverEventsUrl } from '../../app/config'
import { Sidebar } from './Sidebar'
import styles from './AppShell.module.css'

export function AppShell() {
  useServerEvents(serverEventsUrl)
  return (
    <div className={styles.shell}>
      <Sidebar />
      <main className={styles.main}>
        <div className={styles.content}>
          <Outlet />
        </div>
      </main>
    </div>
  )
}
