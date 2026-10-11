import { LockIcon } from 'lucide-react'

import { useConsistencyRules, useUpdateConsistencyRule, type components } from '@/data'

type Rule = components['schemas']['RuleInfo']
type RuleSeverity = Rule['severity']

const SEVERITY_LABEL: Record<RuleSeverity, string> = {
  error: 'Error (blocks saving)',
  warning: 'Warning',
  off: 'Off',
}
const SELECT_CLASS =
  'h-8 rounded-md border border-input bg-transparent px-2 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-60'

function isRuleSeverity(value: string): value is RuleSeverity {
  return value === 'error' || value === 'warning' || value === 'off'
}

function RuleRow({ vault, rule }: { vault: string; rule: Rule }) {
  const update = useUpdateConsistencyRule(vault)
  return (
    <li className="grid grid-cols-[1fr_auto] items-start gap-x-4 gap-y-1 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium">
          {rule.title}
          {rule.findings > 0 && (
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              {rule.findings === 1 ? '1 open finding' : `${rule.findings} open findings`}
            </span>
          )}
        </p>
        <p className="text-sm text-muted-foreground">{rule.description}</p>
      </div>
      <div className="flex items-center gap-1.5">
        {!rule.configurable && <LockIcon className="size-4 text-muted-foreground" aria-hidden />}
        <select
          aria-label={`${rule.title} severity`}
          title={rule.configurable ? undefined : 'A hard rule: always an error'}
          className={SELECT_CLASS}
          disabled={!rule.configurable || update.isPending}
          value={rule.severity}
          onChange={(event) => {
            const value = event.target.value
            if (!isRuleSeverity(value)) return
            update.mutate({
              rule: rule.id,
              // Choosing the default again clears the override.
              severity: value === rule.default_severity ? null : value,
            })
          }}
        >
          {(['error', 'warning', 'off'] as const).map((severity) => (
            <option key={severity} value={severity}>
              {SEVERITY_LABEL[severity]}
              {severity === rule.default_severity ? ' (default)' : ''}
            </option>
          ))}
        </select>
      </div>
    </li>
  )
}

/**
 * Settings → Consistency (consistency.md §5): the rules grouped by owner, each with its
 * description and a severity selector; hard rules are locked.
 */
export function ConsistencySettings({ vault }: { vault: string }) {
  const rules = useConsistencyRules(vault)
  if (rules.isPending) return <p className="text-sm text-muted-foreground">Loading rules…</p>
  const groups = new Map<string, Rule[]>()
  for (const rule of rules.data?.items ?? []) {
    groups.set(rule.owner, [...(groups.get(rule.owner) ?? []), rule])
  }
  const owners = [...groups.keys()].sort((a, b) =>
    a === 'core' ? -1 : b === 'core' ? 1 : a.localeCompare(b),
  )
  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-muted-foreground">
        Errors block saving unless you save anyway with a note; warnings are only listed. Hard rules
        protect the time model and can’t be changed.
      </p>
      {owners.map((owner) => (
        <section key={owner} aria-label={owner === 'core' ? 'Core rules' : `${owner} rules`}>
          <h3 className="text-sm font-semibold">{owner === 'core' ? 'Core' : owner}</h3>
          <ul className="divide-y">
            {(groups.get(owner) ?? []).map((rule) => (
              <RuleRow key={rule.id} vault={vault} rule={rule} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
