interface Props {
  message?: string
  subtext?: string
  detail?: string
  attempt?: number
  maxAttempts?: number
}

export default function LoadingSpinner({
  message = 'Jūsų dokumentas tvarkomas…',
  subtext,
  detail,
  attempt,
  maxAttempts,
}: Props) {
  return (
    <div className="processing-page">
      <div className="spinner" role="status" aria-label="Vyksta dokumento tvarkymas" />
      <h2>{message}</h2>
      {subtext && <p>{subtext}</p>}
      {detail && (
        <div className="processing-status" aria-live="polite">
          <span>Dabar atliekama</span>
          <strong>{detail}</strong>
          {attempt !== undefined && maxAttempts !== undefined && (
            <small>{attempt} bandymas iš {maxAttempts}</small>
          )}
        </div>
      )}
    </div>
  )
}
