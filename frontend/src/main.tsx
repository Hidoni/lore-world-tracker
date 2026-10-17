import { createHashHistory, RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { AppProviders } from '@/app/providers'
import { createAppRouter } from '@/app/router'
import { createStaticDataSource, createStaticFetch, loadStaticFiles, staticConfig } from '@/data'
import { initTheme } from '@/lib/theme'

import '@/styles/globals.css'

initTheme()

const element = document.getElementById('root')
if (!element) throw new Error('#root element missing from index.html')
const root = element

// A static export (`lore vault export-static`) reads its files and routes by the URL's hash, so
// any static host serves it from any folder (ADR 0016).
const exported = staticConfig()
if (exported) {
  // The export's answers by API URL, for checking an export against the server (e2e).
  Object.assign(window, { loreStaticFetch: createStaticFetch(exported.dataUrl) })
}

function render() {
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
}

// The export's downloads (media files, CSVs) are listed before the first link to one is drawn.
if (exported) void loadStaticFiles(exported.dataUrl, exported.vault).then(render)
else render()
