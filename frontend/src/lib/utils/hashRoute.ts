import { useSyncExternalStore } from 'react'

function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener)
  return () => window.removeEventListener('hashchange', listener)
}

function currentPath(): string {
  const path = window.location.hash.replace(/^#/, '')
  return path === '' ? '/' : path
}

// The route left by the last navigation, kept here because a page cannot see where it came from. This listener is
// registered when the module loads, before React subscribes, so it runs first and a page already reads the new value.
let lastPath = currentPath()
let previousPath: string | null = null
window.addEventListener('hashchange', () => {
  previousPath = lastPath
  lastPath = currentPath()
})

/** The route the app came from on the last navigation; null on the first load (a reload has no previous route). */
export function previousRoute(): string | null {
  return previousPath
}

/** Current hash route, e.g. "#/crew" -> "/crew". */
export function useHashRoute(): string {
  return useSyncExternalStore(subscribe, currentPath)
}

export function navigate(path: string): void {
  window.location.hash = path
}
