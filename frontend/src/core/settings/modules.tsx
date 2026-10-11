import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'
import { ApiError, useMutations, useRegistry, useSetModule, type components } from '@/data'

import { Section } from './shared'

type ModuleState = components['schemas']['ModuleState']

/** The modules `id` needs that are off (transitively), in dependency order. */
export function missingDependencies(modules: readonly ModuleState[], id: string): ModuleState[] {
  const byId = new Map(modules.map((module) => [module.id, module]))
  const found: ModuleState[] = []
  const visit = (key: string) => {
    for (const dependency of byId.get(key)?.depends_on ?? []) {
      const module = byId.get(dependency)
      if (module === undefined || found.includes(module)) continue
      visit(dependency)
      if (!module.enabled) found.push(module)
    }
  }
  visit(id)
  return found
}

/** The enabled modules that need `id` (transitively): disabling it disables them too. */
export function enabledDependents(modules: readonly ModuleState[], id: string): ModuleState[] {
  const found: ModuleState[] = []
  const visit = (key: string) => {
    for (const module of modules) {
      if (module.enabled && module.depends_on.includes(key) && !found.includes(module)) {
        found.push(module)
        visit(module.id)
      }
    }
  }
  visit(id)
  return found
}

interface Pending {
  module: ModuleState
  enable: boolean
  /** Also switched by the request: dependencies (enable) or dependents (disable). */
  others: ModuleState[]
}

/**
 * Module toggles (modules.md §4): enabling also enables what a module needs, disabling also
 * disables what needs it; both ask first. Data is never deleted: a disabled module's entities
 * and links are hidden until it's enabled again.
 */
export function ModulesSettings({ vault }: { vault: string }) {
  const editable = useMutations() !== null
  const registry = useRegistry(vault)
  const setModule = useSetModule(vault)
  const [pending, setPending] = useState<Pending | null>(null)
  const modules = (registry.data?.modules ?? []).filter((module) => module.id !== 'core')
  const nameOf = (id: string) => modules.find((module) => module.id === id)?.name ?? id

  const apply = ({ module, enable, others }: Pending) => {
    setModule.mutate(
      { module: module.id, enabled: enable, ...(enable ? {} : { cascade: others.length > 0 }) },
      {
        onSuccess: (result) => {
          setPending(null)
          const switched = enable ? result.enabled : result.disabled
          toast.success(
            `${enable ? 'Enabled' : 'Disabled'} ${switched.map(nameOf).join(', ') || module.name}`,
          )
        },
        onError: (error) => {
          // Someone enabled a dependent meanwhile: ask again with the server's list.
          if (error instanceof ApiError && error.code === 'module_has_dependents') {
            const ids = (error.context.dependents as string[] | undefined) ?? []
            setPending({
              module,
              enable,
              others: modules.filter((candidate) => ids.includes(candidate.id)),
            })
            return
          }
          setPending(null)
          toast.error(error.message)
        },
      },
    )
  }

  const toggle = (module: ModuleState, enable: boolean) => {
    const others = enable
      ? missingDependencies(modules, module.id)
      : enabledDependents(modules, module.id)
    const request = { module, enable, others }
    if (others.length > 0) setPending(request)
    else apply(request)
  }

  return (
    <Section
      title="Modules"
      description="Turn parts of the app on or off for this vault. Turning a module off hides its entities, fields and links; nothing is deleted."
    >
      {registry.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
      {!registry.isPending && modules.length === 0 && (
        <p className="text-sm text-muted-foreground">This server has no optional modules.</p>
      )}
      <ul className="flex flex-col divide-y">
        {modules.map((module) => {
          const id = `module-${module.id}`
          return (
            <li key={module.id} className="flex items-start gap-3 py-3">
              <Switch
                id={id}
                checked={module.enabled}
                disabled={!editable || setModule.isPending}
                onCheckedChange={(checked) => {
                  toggle(module, checked)
                }}
                aria-describedby={`${id}-description`}
              />
              <div className="flex flex-col">
                <label htmlFor={id} className="font-medium">
                  {module.name}
                </label>
                <p id={`${id}-description`} className="text-sm text-muted-foreground">
                  {module.description}
                  {module.depends_on.length > 0 &&
                    ` Needs ${module.depends_on.map(nameOf).join(', ')}.`}
                </p>
              </div>
            </li>
          )
        })}
      </ul>
      {pending && (
        <Dialog
          open
          onOpenChange={(open) => {
            if (!open) setPending(null)
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>
                {pending.enable
                  ? `Enable ${pending.module.name}?`
                  : `Disable ${pending.module.name}?`}
              </DialogTitle>
              <DialogDescription>
                {pending.enable
                  ? `${pending.module.name} needs these modules, which will be enabled too:`
                  : `These modules need ${pending.module.name} and will be disabled too (their data stays):`}
              </DialogDescription>
            </DialogHeader>
            <ul className="list-disc pl-6 text-sm">
              {pending.others.map((module) => (
                <li key={module.id}>{module.name}</li>
              ))}
            </ul>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setPending(null)
                }}
              >
                Cancel
              </Button>
              <Button
                variant={pending.enable ? 'default' : 'destructive'}
                disabled={setModule.isPending}
                onClick={() => {
                  apply(pending)
                }}
              >
                {pending.enable ? 'Enable all' : 'Disable all'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </Section>
  )
}
