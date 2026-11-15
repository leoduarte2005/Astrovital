import styles from './Icon.module.css'

const PATHS = {
  lock: 'M7 11V8a5 5 0 0 1 10 0v3M5 11h14v9H5z',
  chart: 'M4 20V4M4 20h16M8 16l4-5 3 3 5-7',
  diagnosis: 'M3 12h4l2-6 4 12 2-6h6',
  book: 'M5 4h14v16H7a2 2 0 0 1-2-2zM5 18a2 2 0 0 1 2-2h12',
  leaf: 'M5 19C5 10 10 5 20 4c0 10-5 15-14 15zM5 19l8-8',
  rocket: 'M12 3c3 2 5 6 5 10l-2 3H9l-2-3c0-4 2-8 5-10zM9 16l-2 4M15 16l2 4',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0',
  chat: 'M4 5h16v11H9l-5 4z',
  close: 'M6 6l12 12M18 6L6 18',
  swap: 'M7 7h12l-3-3M17 17H5l3 3',
  signal: 'M5 12a10 10 0 0 1 14 0M8 15a6 6 0 0 1 8 0M12 19v.01',
  back: 'M15 5l-7 7 7 7',
  send: 'M4 12l16-8-6 16-2-6z',
  expand: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5',
  collapse: 'M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5',
  menu: 'M4 7h16M4 12h16M4 17h16',
  alert: 'M12 4l9 16H3zM12 10v4M12 17v.01',
} as const

export type IconName = keyof typeof PATHS

/** Inline stroke icon; size follows the parent's font-size and colour follows `color`. */
export function Icon({ name }: { name: IconName }) {
  return (
    <svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  )
}
