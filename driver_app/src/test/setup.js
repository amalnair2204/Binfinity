import '@testing-library/jest-dom'

// Stub navigator.vibrate so hooks don't throw in jsdom
if (!('vibrate' in navigator)) {
  Object.defineProperty(navigator, 'vibrate', { value: () => {}, configurable: true })
}

// Stub AudioContext
if (!window.AudioContext) {
  class FakeOsc {
    connect() {}
    start() {}
    stop() {}
    frequency = { value: 0 }
    type = 'sine'
  }
  class FakeGain {
    connect() {}
    gain = {
      setValueAtTime() {},
      exponentialRampToValueAtTime() {},
    }
  }
  class FakeAudioContext {
    state = 'running'
    currentTime = 0
    destination = {}
    createOscillator() { return new FakeOsc() }
    createGain() { return new FakeGain() }
    resume() { return Promise.resolve() }
  }
  window.AudioContext = FakeAudioContext
}
