import type { CSSProperties } from 'react'
import styles from './CrewFigure.module.css'

/** Placeholder mannequin until per-crew images exist. */
export function CrewFigure({ accent }: { accent: string }) {
  return (
    <svg
      className={styles.root}
      viewBox="0 0 100 220"
      style={{ '--figure-accent': accent } as CSSProperties}
      aria-hidden="true"
    >
      <ellipse className={styles.ring} cx="50" cy="210" rx="42" ry="7" />
      <g className={styles.body}>
        <ellipse cx="50" cy="22" rx="14" ry="17" />
        <rect x="45" y="36" width="10" height="12" rx="3" />
        <rect x="28" y="46" width="44" height="64" rx="14" />
        <rect x="11" y="50" width="13" height="62" rx="6.5" transform="rotate(7 17 50)" />
        <rect x="76" y="50" width="13" height="62" rx="6.5" transform="rotate(-7 83 50)" />
        <rect x="30" y="106" width="18" height="98" rx="9" />
        <rect x="52" y="106" width="18" height="98" rx="9" />
      </g>
    </svg>
  )
}
