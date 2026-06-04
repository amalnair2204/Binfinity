import { describe, it, expect } from 'vitest'
import { fillColor, fillColorDim, fillLabel, FILL_LEGEND } from '../lib/colorScale'

describe('fillColor', () => {
  it('returns green below 50', () => {
    expect(fillColor(0)).toBe('#00ff88')
    expect(fillColor(49)).toBe('#00ff88')
  })

  it('returns amber at 50', () => {
    expect(fillColor(50)).toBe('#ffaa00')
    expect(fillColor(74)).toBe('#ffaa00')
  })

  it('returns orange at 75', () => {
    expect(fillColor(75)).toBe('#ff6600')
    expect(fillColor(89)).toBe('#ff6600')
  })

  it('returns red at 90+', () => {
    expect(fillColor(90)).toBe('#ff3355')
    expect(fillColor(100)).toBe('#ff3355')
  })
})

describe('fillColorDim', () => {
  it('returns dimmed variants matching fillColor bands', () => {
    expect(fillColorDim(0)).toBe('#006633')
    expect(fillColorDim(50)).toBe('#7a5200')
    expect(fillColorDim(75)).toBe('#7a3300')
    expect(fillColorDim(90)).toBe('#7a1a2a')
  })
})

describe('fillLabel', () => {
  it('labels each band correctly', () => {
    expect(fillLabel(0)).toBe('NOMINAL')
    expect(fillLabel(50)).toBe('WATCH')
    expect(fillLabel(75)).toBe('WARNING')
    expect(fillLabel(90)).toBe('CRITICAL')
  })
})

describe('FILL_LEGEND', () => {
  it('has 4 entries', () => expect(FILL_LEGEND).toHaveLength(4))

  it('entries have required fields', () => {
    for (const entry of FILL_LEGEND) {
      expect(entry).toHaveProperty('label')
      expect(entry).toHaveProperty('color')
      expect(entry).toHaveProperty('desc')
    }
  })

  it('first entry is green NOMINAL', () => {
    expect(FILL_LEGEND[0].color).toBe('#00ff88')
    expect(FILL_LEGEND[0].desc).toBe('NOMINAL')
  })
})
