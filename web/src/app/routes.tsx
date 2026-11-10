import type { ComponentType } from 'react'
import type { RouteObject } from 'react-router'
import { AppShell } from '../components/shell/AppShell'
import { RouteError } from '../components/shell/RouteError'
import { HomePage } from '../pages/home/HomePage'
import { NotFoundPage } from '../pages/Placeholder'

/**
 * 首页随主包加载；其余页面按路由拆包，打开时再下载（题库、题目页、考点页等体积较大）。
 * 页面文件下载失败（断网、做题龙刚重启）时自动再试一次；仍失败交给 RouteError 显示中文说明。
 * 写法：lazyPage(() => import('...').then((m) => m.Xxx))
 */
const retryDelayMs = 800
export const lazyPage =
  (load: () => Promise<ComponentType>) => async (): Promise<{ Component: ComponentType }> => {
    try {
      return { Component: await load() }
    } catch {
      await new Promise((resolve) => setTimeout(resolve, retryDelayMs))
      return { Component: await load() }
    }
  }

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      {
        // 无路径的一层：页面出错时只替换内容区，侧栏保留
        errorElement: <RouteError />,
        children: [
          { index: true, element: <HomePage /> },
          {
            path: 'papers',
            lazy: lazyPage(() => import('../pages/paperList/PapersPage').then((m) => m.PapersPage)),
          },
          {
            path: 'papers/:paperId',
            lazy: lazyPage(() => import('../pages/paper/PaperLayout').then((m) => m.PaperLayout)),
            children: [
              {
                index: true,
                lazy: lazyPage(() =>
                  import('../pages/paper/PaperOverview').then((m) => m.PaperOverview),
                ),
              },
              {
                path: 'questions',
                lazy: lazyPage(() =>
                  import('../pages/paper/PaperLayout').then((m) => m.FirstQuestionRedirect),
                ),
              },
              {
                path: 'questions/:number',
                lazy: lazyPage(() =>
                  import('../pages/paper/QuestionAnalysisPage').then((m) => m.QuestionAnalysisPage),
                ),
              },
              {
                path: 'summary',
                lazy: lazyPage(() =>
                  import('../pages/paper/PaperSummary').then((m) => m.PaperSummary),
                ),
              },
            ],
          },
          {
            path: 'practice',
            lazy: lazyPage(() =>
              import('../pages/practice/PracticePage').then((m) => m.PracticePage),
            ),
          },
          {
            path: 'topics',
            lazy: lazyPage(() => import('../pages/topics/TopicsPage').then((m) => m.TopicsPage)),
          },
          {
            path: 'topics/:topicId',
            lazy: lazyPage(() => import('../pages/topics/TopicsPage').then((m) => m.TopicsPage)),
          },
          {
            path: 'profile',
            lazy: lazyPage(() => import('../pages/Placeholder').then((m) => m.ProfilePage)),
          },
          {
            path: 'bank',
            lazy: lazyPage(() => import('../pages/bank/BankPage').then((m) => m.BankPage)),
          },
          {
            path: 'bank/:bankId/practice',
            lazy: lazyPage(() =>
              import('../pages/bank/FreePracticePage').then((m) => m.FreePracticePage),
            ),
          },
          {
            path: 'settings',
            lazy: lazyPage(() =>
              import('../pages/settings/SettingsPage').then((m) => m.SettingsPage),
            ),
          },
          {
            path: 'help/setup',
            lazy: lazyPage(() =>
              import('../pages/help/SetupHelpPage').then((m) => m.SetupHelpPage),
            ),
          },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
]
