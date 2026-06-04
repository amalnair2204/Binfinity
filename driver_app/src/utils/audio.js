let _audioCtx = null

function getCtx() {
  if (!_audioCtx) {
    try {
      _audioCtx = new (window.AudioContext || window.webkitAudioContext)()
    } catch {
      return null
    }
  }
  return _audioCtx
}

const TONES = {
  overflow: { freq: 880, durationS: 0.3, volume: 0.6 },
  reroute:  { freq: 660, durationS: 0.2, volume: 0.5 },
  shift:    { freq: 440, durationS: 0.5, volume: 0.4 },
}

/**
 * Play a short alert tone using the Web Audio API.
 * type: 'overflow' | 'reroute' | 'shift'
 * No-ops silently when AudioContext is unavailable or blocked.
 */
export function playAlertTone(type) {
  const cfg = TONES[type]
  if (!cfg) return
  try {
    const ctx = getCtx()
    if (!ctx) return
    if (ctx.state === 'suspended') ctx.resume()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.type = 'sine'
    osc.frequency.value = cfg.freq
    gain.gain.setValueAtTime(cfg.volume, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + cfg.durationS)
    osc.start(ctx.currentTime)
    osc.stop(ctx.currentTime + cfg.durationS)
  } catch {
    // blocked by autoplay policy or missing API — ignore
  }
}
