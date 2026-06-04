import { describe, it, expect, vi, beforeEach } from 'vitest'
import { playAlertTone } from '../utils/audio.js'

describe('playAlertTone', () => {
  it('does not throw for known types', () => {
    expect(() => playAlertTone('overflow')).not.toThrow()
    expect(() => playAlertTone('reroute')).not.toThrow()
    expect(() => playAlertTone('shift')).not.toThrow()
  })

  it('is a no-op for unknown type', () => {
    expect(() => playAlertTone('unknown_type')).not.toThrow()
  })

  it('is a no-op when AudioContext is unavailable', () => {
    const saved = window.AudioContext
    delete window.AudioContext
    delete window.webkitAudioContext
    expect(() => playAlertTone('overflow')).not.toThrow()
    window.AudioContext = saved
  })
})
