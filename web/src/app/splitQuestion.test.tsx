import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { questionDetails } from '../mocks/data'
import { json, mockServer } from '../test/server'
import { createQueryClient } from './queryClient'
import { routes } from './routes'

beforeEach(() => localStorage.setItem('zuotilong:onboarding-seen', '1'))
afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('splits a question at the clicked position and submits it with the other rows', async () => {
  const fetch = mockServer({
    routes: (path) => {
      if (path !== '/api/questions/paper-fresh-q1') return undefined
      const base = questionDetails[0]
      return json({
        ...base,
        question: { ...base.question, id: 'paper-fresh-q1', number: '1' },
        evidence_regions: [
          {
            region_index: 0,
            page: 2,
            bbox: [50, 100, 550, 400],
            image_url: '/api/questions/paper-fresh-q1/evidence?region=0',
            image_width: 1000,
            image_height: 600,
            image_origin: [100, 200],
            scale: 2,
          },
        ],
      })
    },
  })
  // 图片显示为 300 像素高，点在离顶部 150 处
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    top: 10,
    height: 300,
    left: 0,
    width: 500,
    bottom: 310,
    right: 500,
    x: 0,
    y: 10,
    toJSON: () => ({}),
  })
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider
        router={createMemoryRouter(routes, { initialEntries: ['/papers/paper-fresh'] })}
      />
    </QueryClientProvider>,
  )
  await userEvent.click(await screen.findByRole('button', { name: '纠正题号' }))
  const editor = await screen.findByRole('dialog', { name: '纠正题号' })
  await userEvent.click(within(editor).getAllByRole('button', { name: '拆成两题' })[0])

  const splitter = await screen.findByRole('dialog', { name: '把第 1 题拆成两题' })
  const image = await within(splitter).findByRole('img', { name: '第 1 题切图' })
  fireEvent.pointerDown(image, { clientY: 160, pointerId: 1 })
  fireEvent.pointerUp(image)
  expect(within(splitter).getByRole('textbox', { name: '下半部分的题号' })).toHaveValue('2')
  await userEvent.click(within(splitter).getByRole('button', { name: '在这里拆开' }))

  // 原第 2、3 题顺延为 3、4
  const numbers = within(editor).getAllByRole('textbox', { name: '题号' })
  await userEvent.clear(numbers[1])
  await userEvent.type(numbers[1], '3')
  await userEvent.clear(numbers[2])
  await userEvent.type(numbers[2], '4')
  expect(within(editor).getByText('拆成第 1 题和第 2 题')).toBeInTheDocument()
  await userEvent.click(within(editor).getByRole('button', { name: '下一步' }))
  expect(within(editor).getByText(/其中拆开了 1 道/)).toBeInTheDocument()
  await userEvent.click(within(editor).getByRole('button', { name: '确认纠正' }))

  const call = fetch.mock.calls.find(([url]) => String(url).includes('/questions/correct'))
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    confirmed: true,
    questions: [
      {
        number: '1',
        question_ids: ['paper-fresh-q1'],
        // (200 + 150 * 600 / 300) / 2 = 250
        split: { page: 2, y: 250, lower_number: '2' },
      },
      { number: '3', question_ids: ['paper-fresh-q2'] },
      { number: '4', question_ids: ['paper-fresh-q3'] },
    ],
    delete_question_ids: [],
  })
})
