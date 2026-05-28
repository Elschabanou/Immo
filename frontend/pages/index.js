import {useState} from 'react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || ''

const FREQUENCIES = [
  {value: 'daily', label: 'Daily'},
  {value: 'threedays', label: '3 Days'},
  {value: 'weekly', label: 'Weekly'},
]

const FEATURES = [
  {title: 'Market Pulse', text: 'Tracking of new listings off of ebay kleinanzeigen.en', icon: null},
  {title: 'AI Filtering', text: 'Zero noise, only relevant listings.', icon: null},
]

function formatPrice(value) {
  if (value === '') return ''
  const numeric = Number(value)
  if (Number.isNaN(numeric)) return value
  return new Intl.NumberFormat('de-DE').format(numeric)
}

export default function Home() {
  const [email, setEmail] = useState('')
  const [frequency, setFrequency] = useState('weekly')
  const [minPrice, setMinPrice] = useState('')
  const [maxPrice, setMaxPrice] = useState('180000')
  const [status, setStatus] = useState({type: '', text: ''})
  const [saving, setSaving] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    setStatus({type: '', text: ''})

    const parsedMax = Number(String(maxPrice).replace(/\./g, ''))
    if (!email.trim()) {
      setStatus({type: 'error', text: 'Bitte E-Mail-Adresse angeben.'})
      return
    }
    if (!Number.isInteger(parsedMax) || parsedMax < 50000) {
      setStatus({type: 'error', text: 'Maximalpreis muss mindestens 50.000 EUR sein.'})
      return
    }

    const payload = {
      email: email.trim(),
      frequency: frequency === 'threedays' ? 'weekly' : frequency,
      maxPriceEur: parsedMax,
    }

    setSaving(true)
    try {
      const response = await fetch(`${API_BASE}/api/subscription`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.error || 'Abo konnte nicht gespeichert werden.')
      setStatus({type: 'success', text: 'Subscription created.'})
    } catch (err) {
      setStatus({type: 'error', text: err.message || 'Unbekannter Fehler.'})
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">Immo Scanner</div>
          <nav className="nav" aria-label="Hauptnavigation">
            <a className="active" href="#setup">Setup</a>
            <a href="/subscriptions/manage/">Subscriptions</a>
          </nav>
          <div className="topbar-actions" aria-label="Status und Profil">
            <span className="icon-button" aria-hidden="true"></span>
            <span className="icon-button" aria-hidden="true"></span>
          </div>
        </div>
      </header>

      <main className="content" id="setup">
        <section className="hero-grid">
          <div>
            <span className="eyebrow">Institutional-Grade Data</span>
            <h1 className="hero-title">Immo Scanner<br/>Newsletter</h1>
            <p className="hero-copy">Automated real estate intelligence delivered to your inbox.</p>

            <div className="feature-tile-row">
              {FEATURES.slice(0,2).map((feature)=> (
                <article className="feature-tile" key={feature.title}>
                  <span className="feature-tile-icon">{feature.icon}</span>
                  <h3>{feature.title}</h3>
                  <p>{feature.text}</p>
                </article>
              ))}
            </div>
          </div>

          <form className="alert-card" onSubmit={submit}>
            <h2>Configure Your Alert</h2>
            <p className="subtitle">Define your investment parameters below.</p>

            <div className="field-group">
              <label className="field-label" htmlFor="recipient">Recipient Address</label>
              <input id="recipient" className="text-input" type="email" placeholder="investor@firm.com" value={email} onChange={(e)=>setEmail(e.target.value)} />
            </div>

            <div className="field-group">
              <span className="field-label">Scan Frequency</span>
              <div className="segmented" role="radiogroup" aria-label="Scan Frequency">
                {FREQUENCIES.map((entry)=> (
                  <button key={entry.value} type="button" className={`select-button ${frequency===entry.value? 'active':''}`} onClick={()=>setFrequency(entry.value)}>{entry.label}</button>
                ))}
              </div>
            </div>

            <div className="field-group">
              <span className="field-label">Price Range (EUR)</span>
              <div className="range-grid">
                <label className="range-input">
                  <span className="range-prefix">€</span>
                  <input className="text-input" inputMode="numeric" placeholder="Min" value={formatPrice(minPrice)} onChange={(e)=>{const v=e.target.value.replace(/[^\d]/g,''); setMinPrice(v)}} />
                </label>
                <label className="range-input">
                  <span className="range-prefix">€</span>
                  <input className="text-input" inputMode="numeric" placeholder="Max" value={formatPrice(maxPrice)} onChange={(e)=>{const v=e.target.value.replace(/[^\d]/g,''); setMaxPrice(v)}} />
                </label>
              </div>
            </div>

            <button className="primary-button" type="submit" disabled={saving}>{saving? 'CREATING...':'CREATE SUBSCRIPTION'}</button>

            <div className="privacy-note"> <span>Encrypted & Private Data Handling</span> </div>

            <div className={`toast ${status.type}`}>{status.text}</div>
          </form>
        </section>
      </main>

      <footer className="footer">
        <div className="footer-inner">
          <div>© 2024 Immo Scanner Intelligence. All rights reserved.</div>
          <div className="footer-links"><a href="#">Privacy Policy</a><a href="#">Terms of Service</a><a href="#">Contact</a></div>
        </div>
      </footer>
    </div>
  )
}
