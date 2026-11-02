import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import 'katex/dist/katex.min.css'
import './styles/global.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <p>做题龙</p>
  </StrictMode>,
)
