import {useEffect, useState} from 'react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || ''

function euro(value){
  return `€${new Intl.NumberFormat('de-DE').format(value)}`
}

export default function Manage(){
  const [subscriptions, setSubscriptions] = useState([])
  const [busyKey, setBusyKey] = useState('')
  const [feedback, setFeedback] = useState({type:'', text:''})
  const [loading, setLoading] = useState(true)

  const loadSubscriptions = async ()=>{
    setLoading(true)
    try{
      const res = await fetch(`${API_BASE}/api/subscriptions`)
      const data = await res.json()
      if(!res.ok) throw new Error(data.error || 'Abos konnten nicht geladen werden.')
      setSubscriptions(data.subscriptions || [])
      setFeedback({type:'', text:''})
    }catch(err){
      setFeedback({type:'error', text: err.message || 'Unbekannter Fehler.'})
    }finally{setLoading(false)}
  }

  useEffect(()=>{loadSubscriptions()}, [])

  const removeSubscription = async (email) =>{
    setBusyKey(`delete-${email}`)
    setFeedback({type:'', text:''})
    try{
      const res = await fetch(`${API_BASE}/api/subscription?email=${encodeURIComponent(email)}`, {method:'DELETE'})
      const data = await res.json()
      if(!res.ok) throw new Error(data.error || 'Abo konnte nicht geloescht werden.')
      setFeedback({type:'success', text:'Subscription removed.'})
      await loadSubscriptions()
    }catch(err){setFeedback({type:'error', text: err.message || 'Unbekannter Fehler.'})}finally{setBusyKey('')}
  }

  const editSubscription = async (row) =>{
    const currentMax = String(row.maxPriceEur || '')
    const nextMaxRaw = window.prompt('Maximalpreis in EUR', currentMax)
    if(nextMaxRaw === null) return
    const nextFrequency = window.prompt('Frequenz (daily, weekly, biweekly, monthly)', row.frequency)
    if(nextFrequency === null) return
    const parsedMax = Number(nextMaxRaw.replace(/\./g, ''))
    if(!Number.isInteger(parsedMax) || parsedMax < 50000){
      setFeedback({type:'error', text:'Maximalpreis muss eine ganze Zahl >= 50.000 sein.'})
      return
    }
    setBusyKey(`edit-${row.email}`)
    setFeedback({type:'', text:''})
    try{
      const res = await fetch(`${API_BASE}/api/subscription`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({email: row.email, frequency: nextFrequency.trim().toLowerCase(), maxPriceEur: parsedMax})})
      const data = await res.json()
      if(!res.ok) throw new Error(data.error || 'Abo konnte nicht aktualisiert werden.')
      setFeedback({type:'success', text:'Subscription updated.'})
      await loadSubscriptions()
    }catch(err){setFeedback({type:'error', text: err.message || 'Unbekannter Fehler.'})}finally{setBusyKey('')}
  }

  const scannerCount = subscriptions.length

  return (
    <div className="page">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">Immo Scanner</div>
          <nav className="nav" aria-label="Hauptnavigation">
            <a href="/">Setup</a>
            <a className="active" href="/subscriptions/manage/">Subscriptions</a>
          </nav>
          <div className="topbar-actions"></div>
        </div>
      </header>

      <main className="content">
        <section className="heading">
          <h1>Manage Subscriptions</h1>
          <p>Monitor and adjust your active real estate newsletter filters.</p>
        </section>

        <section className="layout">
          <aside className="status-card">
            <span className="status-eyebrow">Account Status</span>
            <h2>{scannerCount}<br/>Active Scanners</h2>
            <ul className="status-list">
              <li><span>Premium Data Feed Active</span></li>
              <li><span>Last update 14m ago</span></li>
            </ul>
            <button type="button" className="upgrade">Upgrade Plan</button>
          </aside>

          <div>
            <div className="subscriptions">
              {loading && <div className="empty">Loading subscriptions ...</div>}
              {!loading && subscriptions.length === 0 && <div className="empty">Noch keine aktiven Abos vorhanden.</div>}
              {subscriptions.map((row, index)=> (
                <article className="subscription-item" key={row.subscriptionId || row.email}>
                  <div className="sub-header">
                    <div>
                      <span className="sub-badge">Scanner</span>
                      <span className="sub-location">Stuttgart, DE</span>
                    </div>
                    <div className="sub-actions">
                      <button type="button" onClick={()=>editSubscription(row)} disabled={Boolean(busyKey)}>Edit</button>
                      <button className="delete" type="button" onClick={()=>removeSubscription(row.email)} disabled={Boolean(busyKey)}>Delete</button>
                    </div>
                  </div>
                  <div className="sub-email">{row.email}</div>
                  <div className="sub-meta">
                    <span className="sub-meta-item">{row.frequency}</span>
                    <span className="sub-meta-item">{euro(50000)} - {euro(row.maxPriceEur)}</span>
                  </div>
                </article>
              ))}

              <div className="add-card"><a className="add-link" href="/"> <span className="plus-badge">+</span> <span>Create New Newsletter Scan</span></a></div>
            </div>

            <div className={`feedback ${feedback.type}`}>{feedback.text}</div>
          </div>
        </section>
      </main>
    </div>
  )
}
