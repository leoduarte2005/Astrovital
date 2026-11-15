import { useState, type ReactNode } from 'react'
import { useI18n } from '@/lib/i18n'
import { Modal } from '@/ui/Modal'

interface ExpandableChartProps {
  title: string
  /** Renders the chart. `expanded` is true inside the modal; `onExpand` is set only on the card. */
  renderChart: (expanded: boolean, onExpand?: () => void) => ReactNode
}

/** A chart card whose header button opens the same chart in a large modal. */
export function ExpandableChart({ title, renderChart }: ExpandableChartProps) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  return (
    <>
      {renderChart(false, () => setOpen(true))}
      {open && (
        <Modal size="xl" title={title} closeLabel={t('common.close')} onClose={() => setOpen(false)}>
          {renderChart(true)}
        </Modal>
      )}
    </>
  )
}
