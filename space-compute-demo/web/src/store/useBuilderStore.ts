import { create } from 'zustand'

/**
 * Builder visibility — app-level (not page-level) on purpose: the Twin page
 * unmounts whenever the user visits Overview, and a wizard that reopened on
 * every return would be a nuisance. Opening is therefore a one-time event per
 * session, plus whatever the header chip asks for.
 */
interface BuilderState {
  /** The builder covers the Twin page while true. */
  open: boolean
  /** A satellite has been commissioned (or the wizard dismissed) this
   *  session — the Twin page stops auto-opening it. */
  visited: boolean
  openBuilder: () => void
  closeBuilder: () => void
}

export const useBuilderStore = create<BuilderState>((set) => ({
  open: true,
  visited: false,
  openBuilder: () => set({ open: true }),
  closeBuilder: () => set({ open: false, visited: true }),
}))
