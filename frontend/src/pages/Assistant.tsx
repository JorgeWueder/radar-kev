import { PaperPlaneRight, Warning } from '@phosphor-icons/react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { AiBadge } from '../components/AiBadge'
import { Button, PageHeader, Panel, StatusBadge } from '../components/ui'
import { api, ApiError } from '../lib/api'

interface Answer {
  respuesta: string
  citas: { cve_id: string | null; hostname: string | null }[]
  sin_datos: boolean
  advertencias: string[]
}
interface Turn { role: 'user' | 'assistant'; content: string; answer?: Answer; error?: string }

const EXAMPLES = [
  '¿Qué activos críticos tienen CVEs en KEV con SLA vencido?',
  '¿Cuáles son los 3 activos más expuestos?',
  '¿Cuántos CVEs de KEV hay presentes en mi entorno y cuántos son nuevos esta semana?',
  '¿Qué tickets críticos están abiertos?',
]

export default function Assistant() {
  const status = useQuery({ queryKey: ['ai-status'], queryFn: () => api.get<{ enabled: boolean; provider: string; model: string }>('/ai/status') })
  const [turns, setTurns] = useState<Turn[]>([])
  const [q, setQ] = useState('')
  const end = useRef<HTMLDivElement>(null)

  const ask = useMutation({
    mutationFn: (question: string) =>
      api.post<Answer>('/ai/assistant/chat', {
        question,
        history: turns.filter((t) => !t.error).slice(-6).map((t) => ({ role: t.role, content: t.content })),
      }),
    onSuccess: (a) => setTurns((t) => [...t, { role: 'assistant', content: a.respuesta, answer: a }]),
    onError: (e: Error) =>
      setTurns((t) => [...t, { role: 'assistant', content: '', error: e instanceof ApiError && e.status === 503 ? 'La IA no está disponible en este momento. El resto del sistema sigue funcionando.' : e.message }]),
  })

  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [turns, ask.isPending])

  const send = (question: string) => {
    const text = question.trim()
    if (!text || ask.isPending) return
    setTurns((t) => [...t, { role: 'user', content: text }])
    setQ('')
    ask.mutate(text)
  }

  return (
    <>
      <PageHeader
        title="Asistente de consulta"
        subtitle={status.data ? `Modelo ${status.data.provider === 'ollama' ? 'local' : status.data.provider}: ${status.data.model}. Solo consulta datos del radar (herramientas de solo lectura) y respeta los permisos de su rol.` : 'Pregunte en lenguaje natural sobre exposición, SLA y tickets.'}
      />
      {status.data && !status.data.enabled && (
        <p role="status" className="mb-3 rounded-md bg-warn-soft px-3 py-2 text-[13px] text-warn">La IA está desactivada (LLM_PROVIDER). El radar funciona igual; solo falta el asistente.</p>
      )}
      <Panel className="flex min-h-[420px] flex-col">
        <div className="flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite">
          {turns.length === 0 && (
            <div>
              <p className="mb-2 text-[13px] text-muted">Pruebe con una de estas preguntas:</p>
              <div className="flex flex-wrap gap-2">
                {EXAMPLES.map((e) => (
                  <button key={e} onClick={() => send(e)} className="rounded-md border border-line px-2.5 py-1.5 text-left text-[13px] transition-[transform,background-color] duration-150 hover:bg-sunken active:scale-[0.98]">{e}</button>
                ))}
              </div>
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className={t.role === 'user' ? 'flex justify-end' : ''}>
              {t.role === 'user' ? (
                <p className="max-w-[80%] rounded-lg bg-sunken px-3 py-2 text-[13px]">{t.content}</p>
              ) : t.error ? (
                <p role="alert" className="flex max-w-[85%] items-start gap-2 rounded-lg bg-danger-soft px-3 py-2 text-[13px] text-danger"><Warning size={16} className="mt-0.5 shrink-0" aria-hidden /> {t.error}</p>
              ) : (
                <div className="max-w-[85%] space-y-2">
                  <AiBadge model={status.data?.model} />
                  <p className="whitespace-pre-line break-words text-[13px]">{t.content}</p>
                  {t.answer?.sin_datos && <StatusBadge kind="neutral">Sin datos suficientes</StatusBadge>}
                  {t.answer && t.answer.advertencias.length > 0 && (
                    <ul className="rounded-md bg-warn-soft px-3 py-2 text-[12px] text-warn">
                      {t.answer.advertencias.map((a) => <li key={a}>{a}</li>)}
                    </ul>
                  )}
                  {t.answer && t.answer.citas.length > 0 && (
                    <p className="flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
                      Fuentes:
                      {t.answer.citas.map((c) => (
                        <Link key={`${c.cve_id}${c.hostname}`} to={c.cve_id ? `/kev?q=${c.cve_id}` : `/activos?q=${c.hostname}`} className="rounded bg-sunken px-1.5 py-0.5 font-mono text-ink hover:underline">{c.cve_id ?? c.hostname}</Link>
                      ))}
                    </p>
                  )}
                </div>
              )}
            </div>
          ))}
          {ask.isPending && <p role="status" className="text-[13px] text-muted">Consultando los datos del radar…</p>}
          <div ref={end} />
        </div>
        <form className="flex gap-2 border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); send(q) }}>
          <input aria-label="Pregunta" value={q} maxLength={500} onChange={(e) => setQ(e.target.value)} placeholder="Escriba su pregunta…" className="h-9 flex-1 rounded-md border border-line bg-surface px-3 text-[13px]" />
          <Button type="submit" variant="primary" disabled={!q.trim() || ask.isPending} className="!h-9"><PaperPlaneRight size={15} weight="bold" /> Enviar</Button>
        </form>
      </Panel>
    </>
  )
}
