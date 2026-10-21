import type { Bootstrap, Profile } from './types'

export async function getBootstrap(): Promise<Bootstrap> {
  const response = await fetch('/api/bootstrap')
  if (!response.ok) throw new Error('无法连接本地服务')
  return response.json()
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

export async function uploadPaper(file: File, title: string, examDate: string) {
  const form = new FormData()
  form.append('file', file)
  form.append('title', title)
  form.append('exam_date', examDate)
  const response = await fetch('/api/papers/import', { method: 'POST', body: form })
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

export async function saveDiagnosis(id: string, body: Record<string, unknown>) {
  return postJson<{ profile: Profile }>(`/api/questions/${id}/diagnose`, body)
}

export async function saveReview(body: Record<string, unknown>) {
  return postJson<{ profile: Profile }>('/api/reviews', body)
}

export async function confirmPaper(id: string, numbers: string[], scores: string[], subject: string) {
  return postJson<{ created_questions: number }>(`/api/papers/${id}/confirm`, { numbers, scores, subject })
}
