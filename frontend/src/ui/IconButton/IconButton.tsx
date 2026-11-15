import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Icon, type IconName } from '@/ui/Icon'
import styles from './IconButton.module.css'

interface IconButtonProps {
  icon: IconName
  /** Accessible name and tooltip text (already translated). */
  label: string
  onClick: () => void
  disabled?: boolean
  /** Set when the button toggles a disclosure (drawer, menu). */
  expanded?: boolean
}

interface Anchor {
  top: number
  bottom: number
  centerX: number
}

/** Space between the button and its tooltip, and the minimum distance to the viewport edge (px). */
const GAP = 8
const EDGE = 8

/**
 * Round icon-only button. The label shows as a tooltip on hover (mouse or pen) and keyboard focus.
 * The tooltip is portalled to `document.body` with fixed positioning, so no ancestor's `overflow`,
 * `transform` or stacking context can clip it, and it never adds scroll to the page.
 */
export function IconButton({ icon, label, onClick, disabled = false, expanded }: IconButtonProps) {
  const buttonRef = useRef<HTMLButtonElement>(null)
  const tipRef = useRef<HTMLSpanElement>(null)
  const [anchor, setAnchor] = useState<Anchor | null>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)

  const show = () => {
    const rect = buttonRef.current?.getBoundingClientRect()
    if (!rect) return
    setAnchor({ top: rect.top, bottom: rect.bottom, centerX: rect.left + rect.width / 2 })
  }
  const hide = () => {
    setAnchor(null)
    setPos(null)
  }

  // Measure the tooltip once it is rendered, then place it below the button (above if it would
  // leave the viewport at the bottom) and keep it inside the horizontal viewport edges.
  useLayoutEffect(() => {
    const tip = tipRef.current
    if (!anchor || !tip) return
    const width = tip.offsetWidth
    const height = tip.offsetHeight
    const left = Math.min(Math.max(anchor.centerX - width / 2, EDGE), window.innerWidth - width - EDGE)
    const below = anchor.bottom + GAP
    const top = below + height + EDGE > window.innerHeight ? anchor.top - GAP - height : below
    setPos({ left, top })
  }, [anchor])

  // Scrolling or resizing moves the button under a fixed tooltip: hide it instead of chasing it.
  useEffect(() => {
    if (!anchor) return
    window.addEventListener('scroll', hide, true)
    window.addEventListener('resize', hide)
    return () => {
      window.removeEventListener('scroll', hide, true)
      window.removeEventListener('resize', hide)
    }
  }, [anchor])

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={styles.root}
        aria-label={label}
        aria-expanded={expanded}
        onClick={() => {
          hide()
          onClick()
        }}
        onPointerEnter={(event) => {
          if (event.pointerType !== 'touch') show()
        }}
        onPointerLeave={hide}
        onFocus={(event) => {
          if (event.currentTarget.matches(':focus-visible')) show()
        }}
        onBlur={hide}
        disabled={disabled}
      >
        <Icon name={icon} />
      </button>
      {anchor &&
        createPortal(
          <span
            ref={tipRef}
            className={styles.tooltip}
            style={pos ? { left: pos.left, top: pos.top } : { left: 0, top: 0, visibility: 'hidden' }}
            aria-hidden="true"
          >
            {label}
          </span>,
          document.body,
        )}
    </>
  )
}
