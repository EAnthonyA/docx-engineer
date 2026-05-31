interface Props {
  message?: string
  subtext?: string
}

export default function LoadingSpinner({ message = 'Working on it...', subtext }: Props) {
  return (
    <div className="processing-page">
      <div className="spinner" role="status" aria-label="Loading" />
      <h2>{message}</h2>
      {subtext && <p>{subtext}</p>}
    </div>
  )
}
