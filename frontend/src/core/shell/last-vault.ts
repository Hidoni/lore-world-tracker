import { readStored, writeStored } from '@/lib/storage'

const STORAGE_KEY = 'lore.lastVault'

/** The vault the picker opens by default (frontend.md §4). */
export function lastVault(): string | null {
  return readStored(STORAGE_KEY)
}

export function rememberVault(vaultId: string | null): void {
  writeStored(STORAGE_KEY, vaultId)
}
