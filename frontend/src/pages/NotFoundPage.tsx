import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <main className="not-found-page">
      <section className="not-found-content" aria-labelledby="not-found-title">
        <p className="not-found-code">404</p>
        <p className="not-found-brand">docx-engineer</p>
        <h1 id="not-found-title">There is no document tool at this address.</h1>
        <p>
          This URL is not part of docx-engineer. If you meant to use the app,
          sign in and start from its workspace.
        </p>
        <Link className="btn btn--primary" to="/login">
          Go to sign in
        </Link>
      </section>
    </main>
  )
}
