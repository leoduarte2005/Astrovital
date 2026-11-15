import { useSyncExternalStore } from 'react'

function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener)
  return () => window.removeEventListener('hashchange', listener)
}

function currentPath(): string {
  const path = window.location.hash.replace(/^#/, '')
  return path === '' ? '/' : path
}

/** Current hash route, e.g. "#/crew" -> "/crew". */
export function useHashRoute(): string {
  return useSyncExternalStore(subscribe, currentPath)
}

export function navigate(path: string): void {
  window.location.hash = path
}
