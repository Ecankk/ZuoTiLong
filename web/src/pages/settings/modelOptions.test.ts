import { describe, expect, it } from 'vitest'
import { effortLabel, filterModels, groupModels, modelFamily } from './modelOptions'

const model = (name: string) => ({ id: name.toLowerCase(), name, efforts: ['low', 'high'] })

describe('model options', () => {
  it('names efforts in Chinese and never shows unknown raw values', () => {
    expect(effortLabel('high')).toBe('仔细')
    expect(effortLabel('xhigh')).toBe('非常仔细')
    expect(effortLabel('turbo', ['low', 'turbo'])).toBe('第 2 档')
    expect(effortLabel('turbo')).toBe('其他档位')
  })

  it('groups by name prefix', () => {
    expect(modelFamily('gpt-6-luna')).toBe('gpt-6')
    expect(modelFamily('GPT-5.1-Codex')).toBe('GPT-5.1')
    expect(modelFamily('o3')).toBe('o3')
    expect(modelFamily('my-custom-model')).toBe('my')
  })

  it('only groups long lists with several families', () => {
    const few = [model('gpt-6-luna'), model('o3')]
    expect(groupModels(few)).toEqual([{ family: '', models: few }])
    const many = [
      model('gpt-6-luna'),
      model('gpt-6-sol'),
      model('o3'),
      model('gpt-5.1'),
      model('o3-mini'),
      model('gpt-6-mini'),
      model('local-qwen'),
    ]
    expect(groupModels(many).map((g) => [g.family, g.models.length])).toEqual([
      ['gpt-6', 3],
      ['o3', 2],
      ['gpt-5.1', 1],
      ['local', 1],
    ])
  })

  it('filters by name ignoring case and dashes', () => {
    const items = [model('GPT-6-Luna'), model('o3-mini')]
    expect(filterModels(items, 'gpt6').map((m) => m.name)).toEqual(['GPT-6-Luna'])
    expect(filterModels(items, '  ')).toHaveLength(2)
  })
})
