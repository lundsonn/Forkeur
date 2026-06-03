'use client'
import { useState } from 'react'

type Props = {
  restaurantId: string
  restaurantName: string
}

export default function ClaimForm({ restaurantId, restaurantName }: Props) {
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [url, setUrl] = useState('')
  const [state, setState] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setState('loading')
    try {
      const res = await fetch('/api/claims', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          restaurant_id: restaurantId,
          owner_email: email,
          direct_order_url: url,
        }),
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text)
      }
      setState('success')
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Erreur inconnue')
      setState('error')
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-xs text-stone-400 hover:text-stone-600 underline underline-offset-2 transition-colors"
      >
        Vous êtes le propriétaire de ce restaurant ?
      </button>
    )
  }

  if (state === 'success') {
    return (
      <p className="text-xs text-stone-500 py-2">
        Demande envoyée — nous vérifierons et mettrons à jour votre fiche sous peu.
      </p>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="mt-2 border border-stone-200 rounded-xl p-4 flex flex-col gap-3">
      <p className="text-sm font-semibold text-stone-900">Revendiquer {restaurantName}</p>
      <p className="text-xs text-stone-500">
        Indiquez votre email et votre lien de commande directe. Nous vérifierons avant publication.
      </p>

      <div className="flex flex-col gap-1">
        <label htmlFor="claim-email" className="text-xs font-medium text-stone-700">Email</label>
        <input
          id="claim-email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="vous@votrerestaurant.com"
          className="border border-stone-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="claim-url" className="text-xs font-medium text-stone-700">URL de commande</label>
        <input
          id="claim-url"
          type="url"
          required
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://votrerestaurant.com/commander"
          className="border border-stone-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
        />
      </div>

      {state === 'error' && (
        <p className="text-xs text-red-600">Erreur : {errorMsg}</p>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={state === 'loading'}
          className="px-4 py-2 rounded-lg bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold disabled:opacity-50 transition-colors"
        >
          {state === 'loading' ? 'Envoi…' : 'Envoyer'}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="px-4 py-2 rounded-lg bg-stone-100 hover:bg-stone-200 text-stone-700 text-sm font-semibold transition-colors"
        >
          Annuler
        </button>
      </div>
    </form>
  )
}
