/**
 * Cross-island notification for item changes.
 *
 * The review page is one big island (ReviewBoard) plus the header's SeasonActions.
 * Fetching MAL, running matching or syncing BGM rewrites items under the board,
 * so SeasonActions emits and the board shows a "refresh" hint. Deliberately not an
 * auto-reload, which would yank the list out from under an in-progress review.
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
