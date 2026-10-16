import { describe, expect, it } from 'vitest'

import { dependentModule, fixtureModule } from '@/test/fixture-module'

import { activeModules, collectList, collectRecord } from './activation'
import { defineModule } from './types'

const on = (...ids: string[]) => ids.map((id) => ({ id, enabled: true }))

describe('activeModules', () => {
  it('follows the registry’s enabled flags and dependencies', () => {
    const all = [fixtureModule, dependentModule]
    expect(activeModules(all, on('core', 'fixture', 'dependent')).map((m) => m.id)).toEqual([
      'fixture',
      'dependent',
    ])
    expect(activeModules(all, [...on('dependent'), { id: 'fixture', enabled: false }])).toEqual([])
    expect(activeModules(all, on('fixture')).map((m) => m.id)).toEqual(['fixture'])
    expect(activeModules(all, [])).toEqual([])
  })
})

describe('extension points', () => {
  it('collect every list point in order', async () => {
    const modules = [fixtureModule, dependentModule]
    expect(collectList(modules, 'entityPanels').map((panel) => panel.id)).toEqual([
      'fixture.events', // order 0
      'fixture.first',
      'fixture.later',
    ])
    expect(collectList(modules, 'commands').map((command) => command.id)).toEqual([
      'fixture.polish',
      'dependent.go',
    ])
    expect(collectList(modules, 'navSections')).toHaveLength(1)
    expect(collectList(modules, 'timelineLayers')).toHaveLength(1)
    const [load] = collectList(modules, 'editorExtensions')
    expect(await load?.()).toEqual({ name: 'fixtureMark' })
    expect(collectList(modules, 'settingsPages')).toHaveLength(1)
    expect(collectList([dependentModule], 'navSections')).toEqual([])
  })

  it('collect every keyed point', () => {
    expect(Object.keys(collectRecord([fixtureModule], 'linkTypeRenderers'))).toEqual([
      'fixture.guards',
    ])
    expect(Object.keys(collectRecord([fixtureModule], 'fieldTypeRenderers'))).toEqual([
      'fixture.rune',
    ])
    expect(Object.keys(collectRecord([fixtureModule], 'searchResultRenderers'))).toEqual([
      'fixture.relic',
    ])
    expect(Object.keys(collectRecord([fixtureModule], 'entityHeaderMedia'))).toEqual(['relic'])
    expect(Object.keys(collectRecord([fixtureModule], 'kinds'))).toEqual(['relic'])
    expect(collectRecord([], 'kinds')).toEqual({})
    expect(fixtureModule.graphStyles.nodes.relic.color).toBe('#123456')
    expect(fixtureModule.routes).toBeTypeOf('function')
  })

  it('reject invalid module ids', () => {
    expect(() => defineModule({ id: 'Bad-Id' })).toThrow('invalid module id')
  })
})
