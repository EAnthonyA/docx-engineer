import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <main className="not-found-page">
      <section className="not-found-content" aria-labelledby="not-found-title">
        <p className="not-found-code">404</p>
        <p className="not-found-brand">docx-engineer</p>
        <h1 id="not-found-title">Šio puslapio rasti nepavyko.</h1>
        <p>
          Gali būti, kad nuoroda nebegalioja. Grįžkite į pradžią ir pradėkite nuo dokumento pasirinkimo.
        </p>
        <Link className="btn btn--primary" to="/login">
          Grįžti į pradžią
        </Link>
      </section>
    </main>
  )
}
