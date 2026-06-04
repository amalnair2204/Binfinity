import { describe, it, expect, vi } from 'vitest'
import { OfflineQueue } from '../utils/offlineQueue.js'

describe('OfflineQueue', () => {
  it('starts empty', () => {
    const q = new OfflineQueue()
    expect(q.size()).toBe(0)
  })

  it('enqueue increases size', () => {
    const q = new OfflineQueue()
    q.enqueue({ type: 'collect', truckId: 'T1', nodeId: 'B1' })
    expect(q.size()).toBe(1)
  })

  it('dequeue returns oldest action (FIFO)', () => {
    const q = new OfflineQueue()
    q.enqueue({ type: 'collect', truckId: 'T1', nodeId: 'B1' })
    q.enqueue({ type: 'dump',    truckId: 'T1', nodeId: 'Y1' })
    const first = q.dequeue()
    expect(first.type).toBe('collect')
    expect(first.nodeId).toBe('B1')
    expect(q.size()).toBe(1)
  })

  it('dequeue on empty queue returns undefined', () => {
    const q = new OfflineQueue()
    expect(q.dequeue()).toBeUndefined()
  })

  it('enqueue adds timestamp if absent', () => {
    const q = new OfflineQueue()
    q.enqueue({ type: 'collect', truckId: 'T1', nodeId: 'B1' })
    const item = q.dequeue()
    expect(typeof item.timestamp).toBe('number')
  })

  it('flush calls apiFn for each action and clears queue on success', async () => {
    const q = new OfflineQueue()
    q.enqueue({ type: 'collect', truckId: 'T1', nodeId: 'B1' })
    q.enqueue({ type: 'dump',    truckId: 'T1', nodeId: 'Y1' })
    const apiFn = vi.fn().mockResolvedValue(undefined)
    await q.flush(apiFn)
    expect(apiFn).toHaveBeenCalledTimes(2)
    expect(q.size()).toBe(0)
  })

  it('flush retains failed actions', async () => {
    const q = new OfflineQueue()
    q.enqueue({ type: 'collect', truckId: 'T1', nodeId: 'B1' })
    q.enqueue({ type: 'dump',    truckId: 'T1', nodeId: 'Y1' })
    const apiFn = vi.fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error('network'))
    await q.flush(apiFn)
    expect(q.size()).toBe(1)
    expect(q.dequeue().type).toBe('dump')
  })

  it('flush on empty queue is a no-op', async () => {
    const q = new OfflineQueue()
    const apiFn = vi.fn()
    await q.flush(apiFn)
    expect(apiFn).not.toHaveBeenCalled()
  })
})
