// ESLint rule `lore/no-number-moment`: no `Number()`, `parseInt()`, `parseFloat()` or unary `+` on
// in-world moments (CLAUDE.md rule 1). A moment is a `bigint` after the data layer, or a
// `MomentString` (frontend/src/api/moment.ts) on the wire; JS numbers lose precision past 2^53.
// The one allowed float conversion is pixel projection in `@lore/chronology/viewport`.
import ts from 'typescript'

const CONVERTERS = new Set([
  'Number',
  'parseInt',
  'parseFloat',
  'Number.parseInt',
  'Number.parseFloat',
])

function calleeName(callee) {
  if (callee.type === 'Identifier') return callee.name
  if (
    callee.type === 'MemberExpression' &&
    !callee.computed &&
    callee.object.type === 'Identifier' &&
    callee.property.type === 'Identifier'
  ) {
    return `${callee.object.name}.${callee.property.name}`
  }
  return null
}

function isMomentType(type) {
  if (type.isUnion()) return type.types.some(isMomentType)
  if (type.flags & ts.TypeFlags.BigIntLike) return true
  return type.getProperty('__moment') !== undefined
}

/** @type {import('eslint').Rule.RuleModule} */
export default {
  meta: {
    type: 'problem',
    docs: { description: 'Disallow converting in-world moments to JS numbers' },
    messages: {
      number:
        '{{what}} on a moment loses precision: keep it a bigint (CLAUDE.md rule 1). Pixel ' +
        'projection goes through @lore/chronology/viewport.',
    },
    schema: [],
  },
  create(context) {
    const services = context.sourceCode.parserServices
    if (!services?.program || !services.esTreeNodeToTSNodeMap) return {}
    const checker = services.program.getTypeChecker()
    const isMoment = (node) =>
      isMomentType(checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(node)))

    return {
      CallExpression(node) {
        const name = calleeName(node.callee)
        const [argument] = node.arguments
        if (name === null || !CONVERTERS.has(name) || argument === undefined) return
        if (argument.type !== 'SpreadElement' && isMoment(argument)) {
          context.report({ node, messageId: 'number', data: { what: `${name}()` } })
        }
      },
      UnaryExpression(node) {
        if (node.operator === '+' && isMoment(node.argument)) {
          context.report({ node, messageId: 'number', data: { what: 'Unary +' } })
        }
      },
    }
  },
}
