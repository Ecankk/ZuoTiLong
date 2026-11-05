import type { RouteObject } from 'react-router'
import { AppShell } from '../components/shell/AppShell'
import { HomePage } from '../pages/home/HomePage'
import { FirstQuestionRedirect, PaperLayout } from '../pages/paper/PaperLayout'
import { PaperOverview } from '../pages/paper/PaperOverview'
import { PaperSummary } from '../pages/paper/PaperSummary'
import { QuestionAnalysisPage } from '../pages/paper/QuestionAnalysisPage'
import { FreePracticePage } from '../pages/bank/FreePracticePage'
import { BankPage } from '../pages/bank/BankPage'
import { NotFoundPage, ProfilePage } from '../pages/Placeholder'
import { TopicsPage } from '../pages/topics/TopicsPage'
import { PapersPage } from '../pages/paperList/PapersPage'
import { SettingsPage } from '../pages/settings/SettingsPage'
import { PracticePage } from '../pages/practice/PracticePage'

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'papers', element: <PapersPage /> },
      {
        path: 'papers/:paperId',
        element: <PaperLayout />,
        children: [
          { index: true, element: <PaperOverview /> },
          { path: 'questions', element: <FirstQuestionRedirect /> },
          { path: 'questions/:number', element: <QuestionAnalysisPage /> },
          { path: 'summary', element: <PaperSummary /> },
        ],
      },
      { path: 'practice', element: <PracticePage /> },
      { path: 'topics', element: <TopicsPage /> },
      { path: 'topics/:topicId', element: <TopicsPage /> },
      { path: 'profile', element: <ProfilePage /> },
      { path: 'bank', element: <BankPage /> },
      { path: 'bank/:bankId/practice', element: <FreePracticePage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
