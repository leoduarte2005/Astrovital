import styles from './Hero.module.css'

interface HeroProps {
  title: string
  /** Short line under the title (already translated). */
  tagline?: string
  /** Paragraph under the tagline (already translated). */
  summary?: string
}

/** Title block: a large title, optionally followed by a tagline and a summary. Size and colour come from the kit. */
export function Hero({ title, tagline, summary }: HeroProps) {
  return (
    <header className={styles.root}>
      <h1 className={styles.title}>{title}</h1>
      {tagline && <p className={styles.tagline}>{tagline}</p>}
      {summary && <p className={styles.summary}>{summary}</p>}
    </header>
  )
}
