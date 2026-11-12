import React, { useState, useEffect } from 'react'
import { useRouter } from '../../router/RouterContext'
import { useAuth } from '../../router/AuthContext'
import { api } from '../../api/client'
import { normalizeCandidatePhoto } from '../../components/CandidateCard'
import '../public/Pages.css'

export default function AdminCandidatesPage() {
  const { params, navigate } = useRouter()
  const { adminAuth, adminToken } = useAuth()

  const routeElectionId = params?.electionId || params?.id || ''
  const [electionId, setElectionId] = useState(routeElectionId)
  const [election, setElection] = useState(null)
  const [allElections, setAllElections] = useState([])
  const [candidates, setCandidates] = useState([])

  // Form Fields
  const [name, setName] = useState('')
  const [position, setPosition] = useState('')
  const [department, setDepartment] = useState('')
  const [year, setYear] = useState('')
  const [photoUrl, setPhotoUrl] = useState('')
  const [slogan, setSlogan] = useState('')
  const [manifesto, setManifesto] = useState('')

  // Device File Upload State
  const fileInputRef = React.useRef(null)
  const [selectedImageFile, setSelectedImageFile] = useState(null)
  const [imagePreviewUrl, setImagePreviewUrl] = useState('')
  const [fileUploadError, setFileUploadError] = useState('')
  const [showManualPath, setShowManualPath] = useState(false)

  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)

  const isOfficer = adminAuth?.role === 'OFFICER'

  const handleFileChange = (e) => {
    const file = e.target.files?.[0]
    setFileUploadError('')
    if (!file) return

    const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
    const ext = file.name.split('.').pop()?.toLowerCase()
    const allowedExts = ['jpg', 'jpeg', 'png', 'webp']

    if (!allowedTypes.includes(file.type) && !allowedExts.includes(ext)) {
      setFileUploadError('Unsupported file type. Please select a JPG, JPEG, PNG, or WebP image.')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    if (file.size > 5 * 1024 * 1024) {
      setFileUploadError(`File exceeds 5MB limit (${(file.size / (1024 * 1024)).toFixed(1)} MB). Please choose a smaller image.`)
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    setSelectedImageFile(file)
    const preview = URL.createObjectURL(file)
    setImagePreviewUrl(preview)
    setPhotoUrl('')
  }

  const handleRemoveImage = () => {
    setSelectedImageFile(null)
    if (imagePreviewUrl) {
      URL.revokeObjectURL(imagePreviewUrl)
      setImagePreviewUrl('')
    }
    setFileUploadError('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleCandidatePhotoUpdate = async (candidateIndex, file) => {
    if (!file) return
    setError('')
    setSuccess('')

    const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
    const ext = file.name.split('.').pop()?.toLowerCase()
    const allowedExts = ['jpg', 'jpeg', 'png', 'webp']

    if (!allowedTypes.includes(file.type) && !allowedExts.includes(ext)) {
      setError('Unsupported file type. Please select a JPG, JPEG, PNG, or WebP image.')
      return
    }

    if (file.size > 5 * 1024 * 1024) {
      setError(`File exceeds 5MB limit (${(file.size / (1024 * 1024)).toFixed(1)} MB).`)
      return
    }

    setBusy(true)
    try {
      const formData = new FormData()
      formData.append('photo', file)
      const res = await api.post(`/admin/elections/${electionId}/candidates/${candidateIndex}/photo`, formData, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setSuccess(`Candidate #${candidateIndex + 1} photo updated successfully.`)
      await loadElectionDetails(electionId)
    } catch (err) {
      setError(err.message || 'Failed to update candidate photo.')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (routeElectionId && routeElectionId !== electionId) {
      setElectionId(routeElectionId)
    }
  }, [routeElectionId])

  const loadElectionDetails = async (targetId) => {
    const idToLoad = (targetId || electionId || '').trim()
    if (!adminToken || !idToLoad) return
    setLoading(true)
    try {
      const res = await api.get(`/admin/elections/${encodeURIComponent(idToLoad)}`, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      const electionObj = res?.election || res
      setElection(electionObj)
      setCandidates(res?.candidates || electionObj?.candidates || [])
      setError('')
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setError('Rate limit exceeded. Please retry later.')
      } else if (err?.status === 404 || err?.message?.toLowerCase().includes('not found')) {
        // The requested election ID does not exist on the server (stale, deleted or invalid ID)
        setElection(null)
        setCandidates([])
        if (allElections.length > 0) {
          const fallback = allElections.find((e) => e.status === 'DRAFT') || allElections[0]
          if (fallback && fallback.election_id !== idToLoad) {
            setElectionId(fallback.election_id)
            navigate(`/admin/candidates/${fallback.election_id}`, { replace: true })
            setError('')
            loadElectionDetails(fallback.election_id)
            return
          }
        }
        setError(`Election '${idToLoad}' not found. Please select an active election.`)
      } else {
        setElection(null)
        setCandidates([])
        setError(err.message || `Election '${idToLoad}' not found.`)
      }
    } finally {
      setLoading(false)
    }
  }

  const loadElectionsList = async () => {
    if (!adminToken) return
    try {
      const res = await api.get('/admin/elections', {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      const list = res?.elections || []
      setAllElections(list)

      const targetId = (routeElectionId || electionId || '').trim()
      const exists = list.some((e) => e.election_id === targetId)

      if ((!targetId || !exists) && list.length > 0) {
        // Target election ID not found in current list: auto-select draft or first election
        const fallback = list.find((e) => e.status === 'DRAFT') || list[0]
        setElectionId(fallback.election_id)
        navigate(`/admin/candidates/${fallback.election_id}`, { replace: true })
        setError('')
        await loadElectionDetails(fallback.election_id)
      }
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setError('Rate limit exceeded. Please retry later.')
      }
    }
  }

  useEffect(() => {
    loadElectionsList()
  }, [adminToken])

  useEffect(() => {
    if (electionId) {
      loadElectionDetails(electionId)
    }
  }, [adminToken, electionId])

  const handleAddCandidate = async (e) => {
    e.preventDefault()
    setError('')
    setSuccess('')
    setBusy(true)

    try {
      let finalPhotoUrl = photoUrl.trim()

      if (selectedImageFile) {
        const formData = new FormData()
        formData.append('photo', selectedImageFile)
        const uploadRes = await api.post('/admin/candidates/upload-photo', formData, {
          headers: { Authorization: `Bearer ${adminToken}` },
        })
        if (!uploadRes?.photo_url) {
          throw new Error('Candidate photo upload failed: server did not return a valid photo URL.')
        }
        finalPhotoUrl = uploadRes.photo_url
      }

      const normalizedPhoto = normalizeCandidatePhoto(finalPhotoUrl) || undefined
      await api.post(`/admin/elections/${electionId}/candidates`, {
        name: name.trim(),
        position: position.trim() || undefined,
        department: department.trim() || undefined,
        year: year.trim() || undefined,
        photo_url: normalizedPhoto,
        slogan: slogan.trim() || undefined,
        manifesto: manifesto.trim() || undefined,
      }, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })

      setSuccess(`Candidate "${name}" added successfully with candidate photo. Authoritative candidates hash updated.`)
      // Clear form & file selection
      setName('')
      setPosition('')
      setDepartment('')
      setYear('')
      setPhotoUrl('')
      setSlogan('')
      setManifesto('')
      handleRemoveImage()

      await loadElectionDetails(electionId)
    } catch (err) {
      setError(err.message || 'Failed to add candidate. Note: Election must be in DRAFT state.')
    } finally {
      setBusy(false)
    }
  }

  const handleDeleteCandidate = async (candidateIndex, candidateName) => {
    if (!window.confirm(`Are you sure you want to remove candidate "${candidateName}" from this draft election?`)) {
      return
    }

    setError('')
    setSuccess('')
    setBusy(true)

    try {
      await api.delete(`/admin/elections/${electionId}/candidates/${candidateIndex}`, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setSuccess(`Candidate "${candidateName}" removed. Remaining candidates reindexed.`)
      await loadElectionDetails(electionId)
    } catch (err) {
      setError(err.message || 'Failed to remove candidate.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page-container admin-candidates-page">
      <div className="card">
        <span className="badge badge-accent">BALLOT CANDIDATE REGISTRATION</span>
        <h2 className="card-title">Candidate Directory Management</h2>
        <p>
          Configure and vet candidates during election drafting. You can specify display names, positions, photo paths,
          short introductions, and campaign manifestos. Once scheduled, the candidate set is cryptographically hashed and immutable.
        </p>
      </div>

      {/* Target Election Context */}
      <div className="card" style={{ background: '#FFFFFF' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <span className="badge badge-accent">TARGET ELECTION</span>
            <h3 style={{ margin: '0.4rem 0 0.2rem 0', fontSize: '1.4rem', fontWeight: 800 }}>
              {election?.title || (loading ? 'Loading election...' : (electionId ? `Election ${electionId}` : 'No Election Selected'))}
            </h3>
            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center', marginTop: '0.4rem', fontSize: '0.85rem' }}>
              <span>Election ID: <code style={{ fontFamily: 'monospace', fontWeight: 800 }}>{electionId || 'None'}</code></span>
              {election?.status && (
                <span className={`status-badge status-${election.status.toLowerCase()}`}>
                  {election.status}
                </span>
              )}
              {election?.candidate_count !== undefined && (
                <span>Registered Candidates: <strong>{election.candidate_count}</strong></span>
              )}
            </div>
          </div>

          {allElections.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
              <label htmlFor="election-select" style={{ fontSize: '0.8rem', fontWeight: 700, color: '#374151' }}>
                Select Election:
              </label>
              <select
                id="election-select"
                value={allElections.some((e) => e.election_id === electionId) ? electionId : (allElections[0]?.election_id || '')}
                onChange={(e) => {
                  const newId = e.target.value
                  setElectionId(newId)
                  setError('')
                  navigate(`/admin/candidates/${newId}`)
                }}
                style={{ padding: '0.4rem 0.6rem', border: '2px solid #000', fontWeight: 700, background: '#fff' }}
              >
                {allElections.map((el) => (
                  <option key={el.election_id} value={el.election_id}>
                    {el.title} [{el.status}]
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      </div>

      {error && <div className="alert-box alert-error">{error}</div>}
      {success && <div className="alert-box alert-success">{success}</div>}

      {/* Candidate Photo Instructions Banner */}
      <div className="card" style={{ background: '#FFFDF5', border: '3px solid #000' }}>
        <span className="badge badge-violet">PHOTO PLACEMENT GUIDELINES</span>
        <h4 style={{ margin: '0.5rem 0 0.25rem 0', fontWeight: 900 }}>Candidate Photography Path</h4>
        <p style={{ margin: 0, fontSize: '0.925rem', color: '#374151', lineHeight: 1.5 }}>
          Place candidate image files inside <code>frontend/public/images/candidates/</code> in the project.
          Then specify the relative path below, for example: <code>/images/candidates/candidate-1.jpg</code>.
          Vite automatically serves these files directly at that URL.
        </p>
      </div>

      {/* Add Candidate Form (Officers only) */}
      {isOfficer && (
        <div className="card" style={{ background: '#FFFFFF' }}>
          <h3>
            Add Candidate to {election?.title || (electionId ? `Election #${electionId}` : 'Election')}
            {election?.status === 'DRAFT' ? ' (DRAFT ONLY)' : (election?.status ? ` (${election.status})` : ' (DRAFT ONLY)')}
          </h3>
          {election && election.status !== 'DRAFT' ? (
            <p style={{ color: '#DC2626', fontWeight: 700, marginTop: '0.5rem' }}>
              Candidate modifications are locked. This election is in <strong>{election.status}</strong> state. Candidates can only be added or modified while in DRAFT state.
            </p>
          ) : (
            <form onSubmit={handleAddCandidate} style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '1rem' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1rem' }}>
                {/* Name */}
                <div>
                  <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 800, marginBottom: '0.35rem' }}>
                    Candidate Full Name *
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Jane Doe"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    style={{ width: '100%', padding: '0.6rem', border: '2px solid #000', fontWeight: 600 }}
                    required
                    disabled={busy || !electionId}
                  />
                </div>

                {/* Position */}
                <div>
                  <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 800, marginBottom: '0.35rem' }}>
                    Position / Office
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. President, Vice President"
                    value={position}
                    onChange={(e) => setPosition(e.target.value)}
                    style={{ width: '100%', padding: '0.6rem', border: '2px solid #000', fontWeight: 600 }}
                    disabled={busy || !electionId}
                  />
                </div>

                {/* Department / Party */}
                <div>
                  <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 800, marginBottom: '0.35rem' }}>
                    Department / Affiliation
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Computer Science & Engineering"
                    value={department}
                    onChange={(e) => setDepartment(e.target.value)}
                    style={{ width: '100%', padding: '0.6rem', border: '2px solid #000', fontWeight: 600 }}
                    disabled={busy || !electionId}
                  />
                </div>

                {/* Year */}
                <div>
                  <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 800, marginBottom: '0.35rem' }}>
                    Collegiate Year
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. 3rd Year, Final Year"
                    value={year}
                    onChange={(e) => setYear(e.target.value)}
                    style={{ width: '100%', padding: '0.6rem', border: '2px solid #000', fontWeight: 600 }}
                    disabled={busy || !electionId}
                  />
                </div>
              </div>

              {/* Candidate Photo Upload Section */}
              <div style={{ background: '#F9FAFB', border: '2px solid #000', padding: '1rem', borderRadius: '4px' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 800, marginBottom: '0.5rem' }}>
                  Candidate Photograph
                </label>

                <input
                  type="file"
                  ref={fileInputRef}
                  accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
                  onChange={handleFileChange}
                  style={{ display: 'none' }}
                  disabled={busy || !electionId}
                />

                <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={busy || !electionId}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', fontWeight: 800, padding: '0.5rem 1rem' }}
                  >
                    📁 Choose Image
                  </button>

                  {selectedImageFile && (
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={handleRemoveImage}
                      disabled={busy}
                      style={{ fontSize: '0.8rem', padding: '0.45rem 0.75rem', borderColor: '#DC2626', color: '#DC2626' }}
                    >
                      ✕ Remove Image
                    </button>
                  )}

                  <button
                    type="button"
                    className="btn"
                    onClick={() => setShowManualPath(!showManualPath)}
                    style={{ fontSize: '0.75rem', padding: '0.45rem 0.6rem', background: '#F3F4F6', border: '1px solid #9CA3AF' }}
                  >
                    {showManualPath ? 'Hide Manual Path / Presets' : 'Or Use Manual Path / Presets'}
                  </button>
                </div>

                {fileUploadError && (
                  <div style={{ marginTop: '0.5rem', color: '#DC2626', fontWeight: 700, fontSize: '0.825rem' }}>
                    ⚠️ {fileUploadError}
                  </div>
                )}

                {/* Selected Image Preview & Metadata */}
                {selectedImageFile && imagePreviewUrl && (
                  <div style={{ marginTop: '0.75rem', display: 'flex', alignItems: 'center', gap: '1rem', background: '#FFFFFF', border: '2px solid #000', padding: '0.75rem' }}>
                    <img
                      src={imagePreviewUrl}
                      alt="Candidate preview"
                      style={{ width: '64px', height: '64px', objectFit: 'cover', border: '2px solid #000', borderRadius: '4px' }}
                    />
                    <div>
                      <div style={{ fontWeight: 800, fontSize: '0.9rem', color: '#111827' }}>
                        {selectedImageFile.name}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: '#4B5563', marginTop: '0.2rem' }}>
                        {(selectedImageFile.size / 1024).toFixed(1)} KB • {selectedImageFile.type || 'image'}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: '#059669', fontWeight: 700, marginTop: '0.2rem' }}>
                        ✓ Ready to upload on candidate registration
                      </div>
                    </div>
                  </div>
                )}

                {/* Manual Path / Presets Fallback */}
                {showManualPath && (
                  <div style={{ marginTop: '0.75rem', borderTop: '1px dashed #D1D5DB', paddingTop: '0.75rem' }}>
                    <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: '#4B5563', marginBottom: '0.25rem' }}>
                      Custom Photo URL or Relative Path:
                    </label>
                    <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.35rem', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '0.75rem', fontWeight: 700, color: '#4B5563' }}>Presets:</span>
                      {['/images/candidates/luffy.jpg', '/images/candidates/shanks.jpg', '/images/candidates/bb.jpg', '/images/candidates/joker.jpg'].map((path) => (
                        <button
                          key={path}
                          type="button"
                          className="btn"
                          style={{ padding: '0.15rem 0.5rem', fontSize: '0.7rem', background: '#F3F4F6', border: '1px solid #000' }}
                          onClick={() => {
                            handleRemoveImage()
                            setPhotoUrl(path)
                          }}
                        >
                          {path.split('/').pop()}
                        </button>
                      ))}
                    </div>
                    <input
                      type="text"
                      placeholder="e.g. /images/candidates/luffy.jpg or /api/public/candidate-photo/..."
                      value={photoUrl}
                      onChange={(e) => {
                        handleRemoveImage()
                        setPhotoUrl(e.target.value)
                      }}
                      style={{ width: '100%', padding: '0.5rem', border: '2px solid #000', fontWeight: 600, fontSize: '0.85rem' }}
                      disabled={busy || !electionId}
                    />
                    {photoUrl && !selectedImageFile && (
                      <div style={{ marginTop: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem', background: '#FFFFFF', border: '1px solid #E5E7EB', padding: '0.5rem' }}>
                        <img
                          src={normalizeCandidatePhoto(photoUrl)}
                          alt="Preview"
                          style={{ width: '48px', height: '48px', objectFit: 'cover', border: '2px solid #000' }}
                          onError={(e) => { e.currentTarget.style.display = 'none'; const errSpan = e.currentTarget.nextSibling; if (errSpan) errSpan.style.display = 'inline'; }}
                          onLoad={(e) => { e.currentTarget.style.display = 'block'; }}
                        />
                        <span style={{ display: 'none', color: '#DC2626', fontSize: '0.75rem', fontWeight: 700 }}>
                          ⚠️ Image failed to load from: {normalizeCandidatePhoto(photoUrl)}
                        </span>
                        <span style={{ fontSize: '0.75rem', color: '#059669', fontWeight: 700 }}>
                          Path: {normalizeCandidatePhoto(photoUrl)}
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Short Introduction / Slogan */}
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 800, marginBottom: '0.35rem' }}>
                  Short Introduction / Campaign Tagline
                </label>
                <input
                  type="text"
                  placeholder="e.g. Advancing student advocacy, transparent governance, and improved lab access."
                  value={slogan}
                  onChange={(e) => setSlogan(e.target.value)}
                  style={{ width: '100%', padding: '0.6rem', border: '2px solid #000', fontWeight: 600 }}
                  disabled={busy || !electionId}
                />
              </div>

              {/* Campaign Agenda / Manifesto */}
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 800, marginBottom: '0.35rem' }}>
                  Campaign Agenda & Manifesto (Detailed platform pledges)
                </label>
                <textarea
                  rows={4}
                  placeholder="Enter the candidate's policy agenda, student pledges, and election manifesto."
                  value={manifesto}
                  onChange={(e) => setManifesto(e.target.value)}
                  style={{ width: '100%', padding: '0.6rem', border: '2px solid #000', fontWeight: 600, fontFamily: 'inherit' }}
                  disabled={busy || !electionId}
                />
              </div>

              <div>
                <button className="btn btn-primary" type="submit" disabled={busy || !electionId}>
                  {busy ? 'Registering Candidate...' : '+ Register Candidate to Draft'}
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* Registered Candidates Roster */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <h3 style={{ margin: 0 }}>
            Current Candidate Roster {election?.title ? `– ${election.title}` : ''}
          </h3>
          <span className="badge badge-violet">
            {candidates.length} CANDIDATES
          </span>
        </div>

        {loading ? (
          <p>Loading candidate roster...</p>
        ) : candidates.length === 0 ? (
          <p>No candidates registered for {election?.title || (electionId ? `Election #${electionId}` : 'selected election')}.</p>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '1.5rem' }}>
            {candidates.map((c) => (
              <div key={c.index} className="card" style={{ background: '#FFFFFF', border: '3px solid #000', padding: '1.25rem', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <span className="badge badge-violet">BALLOT #{c.index + 1}</span>
                    {c.year && <span className="badge badge-accent">{c.year}</span>}
                  </div>

                  <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', margin: '0.5rem 0' }}>
                    <div style={{ width: '50px', height: '50px', minWidth: '50px', border: '2px solid #000', overflow: 'hidden', background: '#F3F4F6', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      {normalizeCandidatePhoto(c.photo_url) ? (
                        <img
                          src={normalizeCandidatePhoto(c.photo_url)}
                          alt={c.name}
                          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                          onError={(e) => { e.currentTarget.style.display = 'none'; if (e.currentTarget.nextSibling) e.currentTarget.nextSibling.style.display = 'block'; }}
                        />
                      ) : null}
                      <span style={{ display: normalizeCandidatePhoto(c.photo_url) ? 'none' : 'block', fontWeight: 900, fontSize: '1rem' }}>
                        {c.name ? c.name[0] : 'C'}
                      </span>
                    </div>
                    <div>
                      <h4 style={{ fontSize: '1.2rem', margin: 0, fontWeight: 900 }}>{c.name}</h4>
                      <p style={{ fontWeight: 800, color: '#1F2937', margin: 0, fontSize: '0.85rem' }}>
                        Position: <strong>{c.position || c.department || 'Council Member'}</strong>
                      </p>
                    </div>
                  </div>
                  {c.department && (
                    <p style={{ color: '#4B5563', margin: '0 0 0.5rem 0', fontSize: '0.825rem' }}>
                      Affiliation: {c.department}
                    </p>
                  )}

                  {c.photo_url && (
                    <p style={{ fontSize: '0.75rem', color: '#6B7280', margin: '0 0 0.5rem 0', wordBreak: 'break-all' }}>
                      Photo: <code>{c.photo_url}</code>
                    </p>
                  )}

                  {c.slogan && (
                    <div style={{ background: '#FEF9C3', border: '1px dashed #000', padding: '0.4rem', fontSize: '0.8rem', fontStyle: 'italic', marginBottom: '0.5rem' }}>
                      "{c.slogan}"
                    </div>
                  )}

                  {c.manifesto && (
                    <div style={{ fontSize: '0.825rem', color: '#374151', background: '#F9FAFB', border: '1px solid #E5E7EB', padding: '0.5rem', maxHeight: '100px', overflowY: 'auto' }}>
                      <strong>Manifesto:</strong> {c.manifesto}
                    </div>
                  )}
                </div>

                {isOfficer && election?.status === 'DRAFT' && (
                  <div style={{ marginTop: '1rem', borderTop: '2px solid #E5E7EB', paddingTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
                    <label className="btn btn-secondary" style={{ flex: 1, fontSize: '0.78rem', padding: '0.4rem', textAlign: 'center', cursor: 'pointer', margin: 0, fontWeight: 700 }}>
                      📷 Replace Photo
                      <input
                        type="file"
                        accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
                        style={{ display: 'none' }}
                        onChange={(e) => handleCandidatePhotoUpdate(c.index, e.target.files?.[0])}
                        disabled={busy}
                      />
                    </label>
                    <button
                      className="btn btn-secondary"
                      onClick={() => handleDeleteCandidate(c.index, c.name)}
                      disabled={busy}
                      style={{ flex: 1, fontSize: '0.78rem', padding: '0.4rem', borderColor: '#DC2626', color: '#DC2626' }}
                    >
                      Remove
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
