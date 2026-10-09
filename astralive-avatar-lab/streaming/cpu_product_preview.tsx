// CPU lab adapter. Exercise the real preview hook without a GPU or business API.
import React, { useEffect, useState } from '../../frontend/node_modules/react'
import { createRoot } from '../../frontend/node_modules/react-dom/client'
import { api } from '../../frontend/src/api/client'
import { useLivePreview } from '../../frontend/src/hooks/useLivePreview'
const lab = window as typeof window & { lab: any }
api.exchangeWebRTCOffer = async (sessionId, offer) => {
  lab.lab.log('ProductOffer', { sessionId })
  const answer = await (await fetch('/offer', { method: 'POST', body: JSON.stringify(offer) })).json()
  lab.lab.epoch = answer.epoch
  return answer
}
function Preview() {
  const [session, setSession] = useState<string | null>(null)
  const preview = useLivePreview(session)
  useEffect(() => { lab.lab.start = () => setSession('cpu-persistent-source-session'); lab.lab.element = preview.videoRef.current }, [])
  useEffect(() => { lab.lab.log('ProductPreviewState', { status: preview.status, error: preview.error ? String(preview.error) : null }) }, [preview.status, preview.error])
  return <video ref={preview.videoRef} autoPlay playsInline muted={false} width={512} height={512} />
}
const root = createRoot(document.getElementById('root')!)
root.render(<Preview />)
lab.lab.unmount = () => root.unmount()
