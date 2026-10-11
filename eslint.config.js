// ESLint flat config shared by every npm workspace (frontend, packages/*).
import path from 'node:path'

import js from '@eslint/js'
import boundaries from 'eslint-plugin-boundaries'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'
import tseslint from 'typescript-eslint'

import noNumberMoment from './eslint-rules/no-number-moment.js'

/**
 * Frontend source areas (docs/architecture/frontend.md §2). Each element is one top-level folder of
 * `frontend/src`; boundaries are documented in modules.md §3.
 */
const FRONTEND_ELEMENTS = ['app', 'core', 'data', 'api', 'editor', 'components', 'modules', 'lib']

export default tseslint.config(
  {
    ignores: [
      '**/node_modules/',
      '**/dist/',
      '**/coverage/',
      'backend/',
      'frontend/playwright-report/',
      'frontend/test-results/',
      '**/*.gen.ts',
    ],
  },
  js.configs.recommended,
  tseslint.configs.strictTypeChecked,
  tseslint.configs.stylisticTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        projectService: {
          allowDefaultProject: ['*.js', '*.ts'],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      '@typescript-eslint/consistent-type-imports': 'error',
      '@typescript-eslint/restrict-template-expressions': ['error', { allowNumber: true }],
    },
  },
  {
    files: ['**/*.js'],
    extends: [tseslint.configs.disableTypeChecked],
  },
  {
    files: ['eslint.config.js', 'eslint-rules/**', '**/*.config.{js,ts}'],
    languageOptions: { globals: globals.node },
  },

  // --- frontend (@lore/web) ---
  {
    files: ['frontend/**/*.{ts,tsx}'],
    extends: [jsxA11y.flatConfigs.recommended],
    plugins: {
      'react-hooks': reactHooks,
      boundaries,
      lore: { rules: { 'no-number-moment': noNumberMoment } },
    },
    languageOptions: {
      globals: globals.browser,
    },
    settings: {
      // Both default to process.cwd(); pin them so `eslint` behaves the same from the repo root
      // and from a workspace (`npm run lint -w frontend`).
      'boundaries/root-path': import.meta.dirname,
      'import/resolver': {
        typescript: { project: path.join(import.meta.dirname, 'frontend/tsconfig.json') },
      },
      'boundaries/elements': FRONTEND_ELEMENTS.map((type) => ({
        type,
        pattern: `frontend/src/${type}`,
      })),
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'lore/no-number-moment': 'error',
      'boundaries/dependencies': [
        'error',
        {
          default: 'allow',
          policies: [
            {
              // Core is module-agnostic: modules plug into core, never the reverse.
              from: { element: { type: 'core' } },
              disallow: { to: { element: { type: 'modules' } } },
              message:
                'core must not import modules (modules.md §3): add an extension point instead',
            },
            {
              // Shared building blocks stay below the app and domain layers.
              from: { element: { types: { anyOf: ['lib', 'components'] } } },
              disallow: {
                to: { element: { types: { anyOf: ['app', 'core', 'modules', 'data', 'editor'] } } },
              },
              message:
                'lib and components are shared building blocks and must not import app/domain code',
            },
            {
              // Components read and write through the data layer (DataSource/Mutations), never the
              // API client (frontend.md §5.1).
              from: {
                element: { types: { anyOf: ['core', 'modules', 'editor', 'components', 'lib'] } },
              },
              disallow: { to: { element: { type: 'api' } } },
              message:
                'use the data layer (@/data), not the API client: only data/ and app/ import api/',
            },
            {
              // Only the app shell assembles everything.
              from: { element: { types: { anyOf: ['core', 'data', 'api', 'editor', 'modules'] } } },
              disallow: { to: { element: { type: 'app' } } },
              message: 'only app/ may import app/',
            },
          ],
        },
      ],
    },
  },
  {
    // Modules use core's public APIs and other modules' public.ts only (modules.md §3);
    // frontend/src/test/architecture.test.ts checks those imports against `dependsOn`.
    files: ['frontend/src/modules/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/modules/*/*', '!@/modules/*/public'],
              message: "import another module through its public.ts ('@/modules/<id>/public')",
            },
            {
              group: ['@/core/*/*'],
              message: "import core through its public API ('@/core/<area>')",
            },
          ],
        },
      ],
    },
  },
  {
    // Generated shadcn/ui components are owned but kept close to upstream.
    files: ['frontend/src/components/ui/**'],
    rules: {
      '@typescript-eslint/no-unnecessary-condition': 'off',
    },
  },
  {
    files: [
      'frontend/e2e/**',
      'frontend/scripts/**',
      'packages/*/scripts/**',
      'packages/*/test/**',
      '**/*.test.{ts,tsx}',
    ],
    languageOptions: { globals: globals.node },
  },

  // --- @lore/chronology: pure engine code runs in browsers too (chronology-engine.md §1) ---
  {
    files: ['packages/chronology/src/**/*.ts'],
    ignores: ['**/*.test.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            { group: ['node:*'], message: 'the engine is pure: no Node.js APIs (tests may)' },
          ],
        },
      ],
    },
  },
)
