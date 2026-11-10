import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { expect, it, vi } from 'vitest'
import { ErrorState } from './ErrorState'
import { Skeleton } from './Skeleton'

it('shows a friendly message with retry and a way back, never the raw error', async () => {
  const retry = vi.fn()
  const router = createMemoryRouter([
    {
      path: '*',
      element: (
        <ErrorState
          error={new TypeError('Failed to fetch')}
          onRetry={retry}
          back={{ to: '/papers', label: '回到试卷列表' }}
        />
      ),
    },
  ])
  render(<RouterProvider router={router} />)
  expect(screen.getByRole('alert')).toHaveTextContent('连接中断')
  expect(screen.getByRole('alert')).not.toHaveTextContent('Failed to fetch')
  await userEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(retry).toHaveBeenCalledOnce()
  expect(screen.getByRole('link', { name: '回到试卷列表' })).toHaveAttribute('href', '/papers')
})

it('announces loading once for skeletons', () => {
  render(<Skeleton variant="rows" rows={4} />)
  expect(screen.getByRole('status')).toHaveTextContent('正在读取…')
})
