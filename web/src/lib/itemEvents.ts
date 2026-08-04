/**
 * Cross-island notification for item changes.
 *
 * ItemList and ReviewQueue are separate Astro islands on the same page, so they
 * can't share React state. When one changes an item the other's data goes stale.
 * This lets the stale side show a hint instead of silently lying — deliberately
 * not an auto-refresh, which would yank the queue out from under an in-progress
 * review.
 */

const EVENT = 'bgm:items-changed'

export function emitItemsChanged(source: string) {
  window.dispatchEvent(new CustomEvent(EVENT, { detail: { source } }))
}

/** Subscribe; ignores events this component emitted itself. Returns an unsubscribe fn. */
export function onItemsChanged(self: string, cb: () => void): () => void {
  const handler = (e: Event) => {
    if ((e as CustomEvent<{ source: string }>).detail?.source === self) return
    cb()
  }
  window.addEventListener(EVENT, handler)
  return () => window.removeEventListener(EVENT, handler)
}
