import { useMemo } from 'react'
import { MathText } from '../../components/math/MathText'
import { topicNameMath } from './topicNameMath'

/** 考点名：把 e^x、argmax 这类 ASCII 写法排成公式；没有这类写法时就是普通文字。 */
export function TopicName({ name }: { name: string }) {
  const text = useMemo(() => topicNameMath(name), [name])
  if (text === name && !/\\\(|\\\[|\$/.test(name)) return <>{name}</>
  return <MathText text={text} />
}
