import { describe, it, expect } from 'vitest'
import { haversineM } from '../utils/haversine.js'

describe('haversineM', () => {
  it('returns 0 for identical coordinates', () => {
    expect(haversineM(25.2, 55.2, 25.2, 55.2)).toBe(0)
  })

  it('returns ~111 km per degree latitude', () => {
    const dist = haversineM(0, 0, 1, 0)
    expect(dist).toBeGreaterThan(110_000)
    expect(dist).toBeLessThan(112_000)
  })

  it('is symmetric', () => {
    const d1 = haversineM(25.2, 55.2, 25.3, 55.3)
    const d2 = haversineM(25.3, 55.3, 25.2, 55.2)
    expect(Math.abs(d1 - d2)).toBeLessThan(0.001)
  })

  it('detects 50m threshold correctly', () => {
    // ~0.00045 degrees ≈ 50m at equator
    const near = haversineM(0, 0, 0.0004, 0)
    const far  = haversineM(0, 0, 0.001, 0)
    expect(near).toBeLessThan(50)
    expect(far).toBeGreaterThan(50)
  })

  it('handles negative coordinates (southern hemisphere)', () => {
    const dist = haversineM(-33.8, 151.2, -33.9, 151.3)
    expect(dist).toBeGreaterThan(0)
  })
})
