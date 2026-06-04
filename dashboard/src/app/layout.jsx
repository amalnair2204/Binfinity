import './globals.css'
import 'leaflet/dist/leaflet.css'
import AppShell from '../components/shell/AppShell'

export const metadata = {
  title: 'Binfinity Ops',
  description: 'Fleet Operations Command Center',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ height: '100vh', overflow: 'hidden' }}>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  )
}
