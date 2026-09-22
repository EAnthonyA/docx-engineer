import { useRef, useState } from 'react'

interface Props {
  value: File | null
  onChange: (file: File | null) => void
}

export default function FileDropzone({ value, onChange }: Props) {
  const [dragging, setDragging] = useState(false)
  const [fileError, setFileError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  function selectFile(file: File | null) {
    if (file && !file.name.toLowerCase().endsWith('.docx')) {
      setFileError('Prašome pasirinkti Word dokumentą, kurio pavadinimas baigiasi .docx.')
      return
    }
    setFileError('')
    onChange(file)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    selectFile(file ?? null)
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null
    selectFile(file)
  }

  return (
    <>
      <div
        className={`dropzone${dragging ? ' dropzone--active' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        role="button"
        tabIndex={0}
        aria-label="Pasirinkti Word dokumentą"
        onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".docx"
          style={{ display: 'none' }}
          onChange={handleChange}
          aria-hidden="true"
        />

        {value ? (
          <>
            <div className="dropzone__icon">📄</div>
            <div className="dropzone__label">{value.name}</div>
            <div className="dropzone__hint">Spustelėkite čia, jei norite pasirinkti kitą dokumentą</div>
          </>
        ) : (
          <>
            <div className="dropzone__icon">📂</div>
            <div className="dropzone__label">Spustelėkite čia ir pasirinkite dokumentą</div>
            <div className="dropzone__hint">Taip pat galite nutempti Word (.docx) dokumentą į šį lauką</div>
          </>
        )}
      </div>
      {fileError && <p className="error-text" role="alert">{fileError}</p>}
    </>
  )
}
