// Data layer: DataSource & Mutations, query keys, mappers and hooks (frontend.md §5).
import './query-meta'
export { useMeta, type Meta } from './meta'
export {
  useCreateVault,
  useDeleteVault,
  useRenameVault,
  useVault,
  useVaults,
  type Vault,
  type VaultList,
} from './vaults'
