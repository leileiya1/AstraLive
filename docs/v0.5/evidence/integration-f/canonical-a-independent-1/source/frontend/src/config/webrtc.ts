type IceEnvironment = {
  VITE_WEBRTC_STUN_URLS?: string
  VITE_WEBRTC_TURN_URLS?: string
  VITE_WEBRTC_TURN_USERNAME?: string
  VITE_WEBRTC_TURN_CREDENTIAL?: string
}

function urls(value: string | undefined, schemes: readonly string[]): string[] {
  return (value ?? '').split(',').map(url => url.trim()).filter(url => {
    if (!url) return false
    const scheme = url.slice(0, url.indexOf(':')).toLowerCase()
    const valid = schemes.includes(scheme) && url.length > scheme.length + 1 && !/\s/.test(url)
    if (!valid) console.warn(`Ignoring invalid WebRTC ICE URL: ${url}`)
    return valid
  })
}

export function getWebRTCConfiguration(env: IceEnvironment = import.meta.env as IceEnvironment): RTCConfiguration {
  const iceServers: RTCIceServer[] = []
  const stunUrls = urls(env.VITE_WEBRTC_STUN_URLS, ['stun', 'stuns'])
  if (stunUrls.length) iceServers.push({ urls: stunUrls })

  const turnUrls = urls(env.VITE_WEBRTC_TURN_URLS, ['turn', 'turns'])
  if (turnUrls.length) {
    const username = env.VITE_WEBRTC_TURN_USERNAME?.trim()
    const credential = env.VITE_WEBRTC_TURN_CREDENTIAL?.trim()
    if (Boolean(username) !== Boolean(credential)) {
      console.warn('Ignoring WebRTC TURN URLs: username and credential must be configured together')
    } else {
      iceServers.push({ urls: turnUrls, ...(username ? { username, credential } : {}) })
    }
  }
  return iceServers.length ? { iceServers } : {}
}
