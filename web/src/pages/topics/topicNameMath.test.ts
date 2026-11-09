import { describe, expect, it } from 'vitest'
import { topicNameMath } from './topicNameMath'

describe('topicNameMath', () => {
  it('wraps ASCII powers in math delimiters', () => {
    expect(topicNameMath('e^x 在 0 点的泰勒展开')).toBe('\\(e^x\\) 在 0 点的泰勒展开')
    expect(topicNameMath('(1+x)^α 的广义二项式展开')).toBe('\\((1+x)^α\\) 的广义二项式展开')
    expect(topicNameMath("满足 f'=f^2 时的高阶导数关系")).toBe("满足 \\(f'=f^2\\) 时的高阶导数关系")
    expect(topicNameMath('(1+1/x)^x 在 x→+∞ 时的极限')).toBe('\\((1+1/x)^x\\) 在 x→+∞ 时的极限')
    expect(topicNameMath('实矩阵 A^T A 的对称性')).toBe('实矩阵 \\(A^T\\) A 的对称性')
    expect(topicNameMath('x^10 的导数')).toBe('\\(x^{10}\\) 的导数')
  })

  it('renders argmax as an operator', () => {
    expect(topicNameMath('极大似然估计的 argmax 定义')).toBe('极大似然估计的 \\(\\arg\\max\\) 定义')
  })

  it('leaves plain names and names with delimiters alone', () => {
    expect(topicNameMath('条件概率')).toBe('条件概率')
    expect(topicNameMath('平方根 \\(\\sqrt{a^2-x^2}\\) 的正弦参数化')).toBe(
      '平方根 \\(\\sqrt{a^2-x^2}\\) 的正弦参数化',
    )
  })
})
