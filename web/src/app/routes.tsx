import type { RouteObject } from 'react-router'
import { AppShell } from '../components/shell/AppShell'
import { HomePage } from '../pages/home/HomePage'
import {
  FirstQuestionRedirect,
  PaperLayout,
  PaperOverview,
  PaperSummary,
} from '../pages/paper/PaperLayout'
import { QuestionAnalysisPage } from '../pages/paper/QuestionAnalysisPage'
import {
  BankPage,
  NotFoundPage,
  PapersPage,
  ProfilePage,
  SettingsPage,
  TopicsPage,
} from '../pages/Placeholder'
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
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
