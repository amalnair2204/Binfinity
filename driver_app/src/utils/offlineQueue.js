/**
 * In-memory queue for driver actions (collect / dump) captured while offline.
 * Stored in memory only — queue does not survive a page refresh, which is
 * intentional: a page refresh reconnects the device and the server is
 * authoritative on route state.
 */
export class OfflineQueue {
  constructor() {
    this._queue = []
  }

  /**
   * Add an action to the queue.
   * @param {{ type: 'collect'|'dump', truckId: string, nodeId: string, liters?: number, timestamp: number }} action
   */
  enqueue(action) {
    this._queue.push({ ...action, timestamp: action.timestamp ?? Date.now() })
  }

  /** Remove and return the oldest pending action, or undefined if empty. */
  dequeue() {
    return this._queue.shift()
  }

  /** Number of pending actions. */
  size() {
    return this._queue.length
  }

  /**
   * Attempt to send all queued actions using apiFn.
   * Actions that succeed are removed; failed actions remain for next flush.
   * @param {(action: object) => Promise<void>} apiFn
   */
  async flush(apiFn) {
    const remaining = []
    for (const action of this._queue) {
      try {
        await apiFn(action)
      } catch {
        remaining.push(action)
      }
    }
    this._queue = remaining
  }
}

export const offlineQueue = new OfflineQueue()
