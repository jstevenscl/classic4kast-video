import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('classic4kast-session')
  if (token) config.headers['X-Session-Token'] = token
  return config
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      // Same fix as VOD & DVR Manager's api.ts -- a silent reload on 401
      // used to wipe out whatever action was in flight with zero
      // indication anything went wrong. Surface it instead.
      localStorage.removeItem('classic4kast-session')
      alert('Your session expired or was signed out elsewhere. Whatever you just tried to do did NOT go through -- please log in again and retry it.')
      window.location.reload()
    }
    return Promise.reject(err)
  }
)

export default api
