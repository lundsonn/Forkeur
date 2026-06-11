import '@testing-library/jest-dom'
import React from 'react'
import { vi } from 'vitest'

// Mock next/dynamic to eagerly preload the module and render synchronously.
// React.lazy always suspends at least once (async), which breaks sync test assertions.
// This approach calls fn() at dynamic()-call-time (module load), caches the result,
// and renders the resolved component synchronously once the microtask settles.
vi.mock('next/dynamic', () => ({
  __esModule: true,
  default: (fn: () => Promise<{ default: React.ComponentType<unknown> }>) => {
    let Comp: React.ComponentType<unknown> | null = null
    fn().then(m => { Comp = m.default })

    function DynamicComponent(props: Record<string, unknown>) {
      if (!Comp) return null
      return React.createElement(Comp, props)
    }
    return DynamicComponent
  },
}))
