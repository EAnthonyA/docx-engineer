import { useRef, useState } from 'react'

interface Props {
  value: File | null
  onChange: (file: File | null) => void
}

export default function FileDropzone({ value, onChange }: Props) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file && file.name.toLowerCase().endsWith('.docx')) {
      onChange(file)
    }
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null
    onChange(file)
  }

  return (
    <div
      className={`dropzone${dragging ? ' dropzone--active' : ''}`}
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      role="button"
      tabIndex={0}
      aria-label="Upload .docx file"
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
          <div className="dropzone__hint">Click or drop to replace</div>
        </>
      ) : (
        <>
          <div className="dropzone__icon">📂</div>
          <div className="dropzone__label">Drop your .docx here</div>
          <div className="dropzone__hint">or click to browse</div>
        </>
      )}
    </div>
  )
}
