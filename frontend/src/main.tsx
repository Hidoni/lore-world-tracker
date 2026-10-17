import { createHashHistory, RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { AppProviders } from '@/app/providers'
import { createAppRouter } from '@/app/router'
import { createStaticDataSource, staticConfig } from '@/data'
import { initTheme } from '@/lib/theme'

import '@/styles/globals.css'

initTheme()

const root = document.getElementById('root')
if (!root) throw new Error('#root element missing from index.html')

// A static export (`lore vault export-static`) reads its files and routes by the URL's hash, so
// any static host serves it from any folder (ADR 0016).
const exported = staticConfig()

createRoot(root).render(
  <StrictMode>
    {exported ? (
      <AppProviders dataSource={createStaticDataSource(exported)} mutations={null}>
        <RouterProvider router={createAppRouter(createHashHistory())} />
      </AppProviders>
    ) : (
      <AppProviders>
        <RouterProvider router={createAppRouter()} />
      </AppProviders>
    )}
  </StrictMode>,
)
