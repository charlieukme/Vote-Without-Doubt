import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'

const RouterContext = createContext({
  path: '/',
  navigate: () => {},
  params: {},
})

/**
 * Lightweight, zero-dependency client-side router.
 * Supports window.location, popstate, history.pushState, and parameterized routes.
 */
export function RouterProvider({ children }) {
  const [currentUrl, setCurrentUrl] = useState(() => {
    if (typeof window !== 'undefined' && window.location) {
      return (window.location.pathname || '/') + (window.location.search || '')
    }
    return '/'
  })

  useEffect(() => {
    const handlePopState = () => {
      if (typeof window !== 'undefined' && window.location) {
        setCurrentUrl((window.location.pathname || '/') + (window.location.search || ''))
      }
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  const navigate = useCallback((to) => {
    if (typeof window !== 'undefined' && window.history) {
      window.history.pushState({}, '', to)
    }
    setCurrentUrl(to)
    if (typeof window !== 'undefined') {
      window.scrollTo(0, 0)
    }
  }, [])

  // Simple route matcher to extract path parameters (e.g., /candidates/:id, /admin/candidates/:id)
  const extractParams = useCallback((currentPath) => {
    let pathname = currentPath || ''
    let search = ''
    const qIdx = pathname.indexOf('?')
    if (qIdx !== -1) {
      search = pathname.slice(qIdx + 1)
      pathname = pathname.slice(0, qIdx)
    } else if (typeof window !== 'undefined' && window.location && window.location.search) {
      search = window.location.search.replace(/^\?/, '')
    }

    const queryParams = {}
    if (search) {
      const searchParams = new URLSearchParams(search)
      for (const [key, value] of searchParams.entries()) {
        queryParams[key] = value
      }
    }

    const candidateMatch = pathname.match(/^\/candidates\/([^/]+)$/)
    if (candidateMatch) {
      return { ...queryParams, id: candidateMatch[1] }
    }
    const electionMatch = pathname.match(/^\/election\/([^/]+)$/)
    if (electionMatch) {
      return { ...queryParams, id: electionMatch[1] }
    }
    const adminCandidateMatch = pathname.match(/^\/admin\/candidates\/([^/]+)$/)
    if (adminCandidateMatch) {
      return { ...queryParams, id: adminCandidateMatch[1], electionId: adminCandidateMatch[1] }
    }
    if (queryParams.election_id) {
      return { ...queryParams, id: queryParams.election_id, electionId: queryParams.election_id }
    }
    return queryParams
  }, [])

  // Match routes using window.location.pathname independently from search query parameters
  let pathname = currentUrl || '/'
  let search = ''
  const qIdx = pathname.indexOf('?')
  if (qIdx !== -1) {
    search = pathname.slice(qIdx)
    pathname = pathname.slice(0, qIdx)
  } else if (typeof window !== 'undefined' && window.location && window.location.search) {
    search = window.location.search
  }
  if (!pathname.startsWith('/')) {
    pathname = '/' + pathname
  }

  const value = {
    path: pathname, // Primary route matching path, cleanly isolated from search query string
    pathname,
    search,
    fullPath: currentUrl,
    navigate,
    params: extractParams(currentUrl),
  }

  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>
}

export function useRouter() {
  return useContext(RouterContext)
}

export default RouterContext
