import { expect, it } from 'vitest'
import type { EvidenceRegion } from '../../api/types'
import { nextNumber, splitY } from './SplitQuestion'

const region: EvidenceRegion = {
  region_index: 0,
  page: 1,
  bbox: [50, 100, 550, 400],
  image_url: '/api/questions/q/evidence?region=0',
  image_width: 1000,
  image_height: 600,
  image_origin: [100, 200],
  scale: 2,
}

it('converts a click on the displayed image to the page position', () => {
  // 图片显示高度 300（缩小一半），点在离顶部 150 处：(200 + 150 * 600 / 300) / 2 = 250
  expect(splitY(region, 150, 300)).toBe(250)
  // 按原始像素显示时 H = image_height
  expect(splitY(region, 0, 600)).toBe(100)
})

it('suggests the next number for the lower part', () => {
  expect(nextNumber('1')).toBe('2')
  expect(nextNumber('第一题')).toBe('')
})
