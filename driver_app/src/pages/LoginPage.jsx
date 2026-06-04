import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import useDriverStore from '../store/driverStore.js'
import { driverSocket } from '../api/socket.js'

/**
 * Login screen — truck ID entry only, no password.
 * Truck ID is normalised to uppercase before storing.
 */
export default function LoginPage() {
  const [input, setInput] = useState('')
  const [error, setError] = useState('')
  const setTruckId = useDriverStore((s) => s.setTruckId)
  const startShift = useDriverStore((s) => s.startShift)
  const navigate = useNavigate()

  function handleStart(e) {
    e.preventDefault()
    const id = input.trim().toUpperCase()
    if (!id) {
      setError('Enter your truck ID')
      return
    }
    setTruckId(id)
    startShift()
    driverSocket.connect(id)
    navigate('/shift', { replace: true })
  }

  return (
    <div className="min-h-screen bg-app-bg flex flex-col items-center justify-center px-6">
      {/* Logo / hero */}
      <div className="mb-12 text-center select-none">
        <div className="text-7xl mb-5">🚛</div>
        <h1 className="text-5xl font-black text-white tracking-tight leading-none">Binfinity</h1>
        <p className="text-app-secondary text-xl mt-3 font-medium">Driver Navigation</p>
      </div>

      {/* Login form */}
      <form onSubmit={handleStart} className="w-full max-w-sm" noValidate>
        <label
          htmlFor="truck-id"
          className="block text-app-secondary text-sm font-bold uppercase tracking-widest mb-3"
        >
          Your Truck ID
        </label>

        <input
          id="truck-id"
          type="text"
          inputMode="text"
          value={input}
          onChange={(e) => { setInput(e.target.value); setError('') }}
          placeholder="T1  ·  T2  ·  TRK-007"
          className="w-full bg-app-card border-2 border-app-border text-white text-2xl font-black
            rounded-2xl px-5 py-5 outline-none focus:border-app-green transition-colors
            placeholder:text-app-secondary/40 uppercase tracking-widest"
          autoCapitalize="characters"
          autoCorrect="off"
          autoComplete="off"
          spellCheck="false"
          autoFocus
        />

        {error && (
          <p role="alert" className="text-red-400 text-sm mt-2 font-semibold">{error}</p>
        )}

        <button
          type="submit"
          className="mt-6 w-full bg-app-green text-black font-black text-2xl tracking-tight
            py-6 rounded-2xl shadow-xl active:scale-[0.97] transition-transform select-none"
        >
          START SHIFT
        </button>
      </form>
    </div>
  )
}
