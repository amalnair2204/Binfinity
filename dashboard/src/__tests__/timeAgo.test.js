import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { timeAgo, formatTime, formatDate } from '../lib/timeAgo'

const BASE = new Date('2025-01-15T12:00:00.000Z')

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(BASE)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('timeAgo', () => {
  it('returns — for null', () => expect(timeAgo(null)).toBe('—'))
  it('returns — for undefined', () => expect(timeAgo(undefined)).toBe('—'))

  it('returns "just now" within 5 seconds', () => {
    const ts = new Date(BASE.getTime() - 3_000)
    expect(timeAgo(ts)).toBe('just now')
  })

  it('returns seconds for 5s–60s', () => {
    const ts = new Date(BASE.getTime() - 30_000)
    expect(timeAgo(ts)).toBe('30s ago')
  })

  it('returns minutes for 1m–60m', () => {
    const ts = new Date(BASE.getTime() - 5 * 60_000)
    expect(timeAgo(ts)).toBe('5m ago')
  })

  it('returns hours for 1h–24h', () => {
    const ts = new Date(BASE.getTime() - 3 * 3_600_000)
    expect(timeAgo(ts)).toBe('3h ago')
  })

  it('returns days beyond 24h', () => {
    const ts = new Date(BASE.getTime() - 2 * 86_400_000)
    expect(timeAgo(ts)).toBe('2d ago')
  })

  it('accepts ISO string', () => {
    const iso = new Date(BASE.getTime() - 45_000).toISOString()
    expect(timeAgo(iso)).toBe('45s ago')
  })
})

describe('formatTime', () => {
  it('returns HH:MM:SS string', () => {
    const result = formatTime(BASE)
    expect(result).toMatch(/^\d{2}:\d{2}:\d{2}$/)
  })
})

describe('formatDate', () => {
  it('returns a non-empty string', () => {
    expect(typeof formatDate(BASE)).toBe('string')
    expect(formatDate(BASE).length).toBeGreaterThan(0)
  })
})
