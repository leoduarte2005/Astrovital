import { useCallback, useEffect, useState } from 'react'
import { APP_NAME } from '@/app/constants'
import { getDataSource } from '@/lib/data'
import { useSession } from '@/lib/data/session'
import { useI18n, type MessageKey } from '@/lib/i18n'
import type { Book } from '@/lib/data/mock/bookCatalog'
import { AlertBadge } from '@/ui/AlertBadge'
import { Button } from '@/ui/Button'
import { Card } from '@/ui/Card'
import styles from './LeisurePage.module.css'

/** Books chosen for the crew member, from the genres they like. Download is simulated: only a notice. */
export default function LeisurePage() {
  const { t } = useI18n()
  const crewId = useSession((state) => state.activeCrew?.crewId ?? null)
  const [books, setBooks] = useState<Book[] | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    if (!crewId) return
    let active = true
    getDataSource()
      .listBookSuggestions(crewId)
      .then((list) => {
        if (active) setBooks(list)
      })
    return () => {
      active = false
    }
  }, [crewId])

  const dismiss = useCallback(() => setNotice(null), [])

  return (
    <main className={styles.root}>
      <header className={styles.header}>
        <p className={styles.brand}>{APP_NAME}</p>
        <h1 className={styles.title}>{t('leisure.title')}</h1>
        <p className={styles.subtitle}>{t('leisure.subtitle')}</p>
      </header>
      {books === null ? (
        <p className={styles.subtitle}>{t('common.loading')}</p>
      ) : books.length === 0 ? (
        <p className={styles.subtitle}>{t('leisure.empty')}</p>
      ) : (
        <div className={styles.grid}>
          {books.map((book) => (
            <BookCard key={book.id} book={book} onDownload={() => setNotice(t('leisure.download.notice', { title: book.title }))} />
          ))}
        </div>
      )}
      {notice !== null && <AlertBadge message={notice} onDismiss={dismiss} />}
    </main>
  )
}

function BookCard({ book, onDownload }: { book: Book; onDownload: () => void }) {
  const { t } = useI18n()
  return (
    <Card label={book.title} className={styles.book}>
      <div className={styles.cover}>
        <h2 className={styles.name}>{book.title}</h2>
        <p className={styles.text}>{book.author}</p>
      </div>
      <p className={styles.genre}>{t(`genre.${book.genre}` as MessageKey)}</p>
      <Button icon="download" onClick={onDownload}>
        {t('leisure.download')}
      </Button>
    </Card>
  )
}
