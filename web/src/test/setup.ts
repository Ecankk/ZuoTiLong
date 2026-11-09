import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => cleanup())

// 页面按路由懒加载：并发跑全部测试时机器负载高，等待上限放宽到 3 秒，避免偶发超时
configure({ asyncUtilTimeout: 3000 })

// jsdom 没有实现滚动
Element.prototype.scrollIntoView = () => {}
