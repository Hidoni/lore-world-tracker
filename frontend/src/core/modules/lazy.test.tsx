import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { isLazyComponent, lazyComponent, loadEditorExtensions } from './lazy'

function Hello({ name }: { name: string }) {
  return <p>Hello {name}</p>
}

describe('lazyComponent', () => {
  it('loads with the first render, through Suspense', async () => {
    const Lazy = lazyComponent(() => Promise.resolve(Hello), <p>Loading…</p>)
    render(<Lazy name="Ilsa" />)
    expect(screen.getByText('Loading…')).toBeInTheDocument()
    expect(await screen.findByText('Hello Ilsa')).toBeInTheDocument()
    expect(isLazyComponent(Lazy)).toBe(true)
    expect(isLazyComponent(Hello)).toBe(false)
  })

  it('renders at once once preloaded: no fallback', async () => {
    const Lazy = lazyComponent(() => Promise.resolve(Hello), <p>Loading…</p>)
    await Lazy.preload()
    render(<Lazy name="Varn" />)
    expect(screen.getByText('Hello Varn')).toBeInTheDocument()
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
  })

  it('tries again after a failed load', async () => {
    let calls = 0
    const Lazy = lazyComponent(() => {
      calls += 1
      return calls === 1 ? Promise.reject(new Error('offline')) : Promise.resolve(Hello)
    })
    await expect(Lazy.preload()).rejects.toThrow('offline')
    await Lazy.preload()
    expect(calls).toBe(2)
    render(<Lazy name="again" />)
    expect(screen.getByText('Hello again')).toBeInTheDocument()
  })
})

describe('loadEditorExtensions', () => {
  it('loads each extension once and returns the same promise for the same set', async () => {
    let calls = 0
    const loader = () => {
      calls += 1
      return Promise.resolve({ name: 'ext' } as never)
    }
    const first = loadEditorExtensions([loader])
    expect(loadEditorExtensions([loader])).toBe(first)
    expect(await first).toHaveLength(1)
    // React's use() reads a settled set without suspending.
    expect((first as { status?: string }).status).toBe('fulfilled')
    expect(calls).toBe(1)
  })
})
