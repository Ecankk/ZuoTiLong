import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { expect, it, vi } from 'vitest'
import { RouteError } from '../components/shell/RouteError'
import { lazyPage } from './routes'

it('retries a page file once and then shows a Chinese reload card instead of the router error page', async () => {
  const load = vi.fn(() =>
    Promise.reject(
      new TypeError('Failed to fetch dynamically imported module: /assets/BankPage.js'),
    ),
  )
  const router = createMemoryRouter(
    [
      {
        path: '/',
        errorElement: <RouteError />,
        children: [{ path: 'bank', lazy: lazyPage(load) }],
      },
    ],
    { initialEntries: ['/bank'] },
  )
  render(<RouterProvider router={router} />)
  const alert = await screen.findByRole('alert', {}, { timeout: 4000 })
  expect(alert).toHaveTextContent('页面没能打开')
  expect(alert).toHaveTextContent('连不上做题龙')
  expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument()
  expect(document.body.textContent).not.toMatch(/Unexpected Application Error|Failed to fetch/)
  expect(load).toHaveBeenCalledTimes(2)
})

it('loads the page when the retry succeeds', async () => {
  const Page = () => <p>题库页面</p>
  const load = vi
    .fn<() => Promise<typeof Page>>()
    .mockRejectedValueOnce(new TypeError('Failed to fetch dynamically imported module'))
    .mockResolvedValueOnce(Page)
  const router = createMemoryRouter(
    [
      {
        path: '/',
        errorElement: <RouteError />,
        children: [{ path: 'bank', lazy: lazyPage(load) }],
      },
    ],
    { initialEntries: ['/bank'] },
  )
  render(<RouterProvider router={router} />)
  expect(await screen.findByText('题库页面', {}, { timeout: 4000 })).toBeInTheDocument()
})
