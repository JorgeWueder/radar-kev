Redacta el resumen ejecutivo para la gerencia (no técnica) con los datos de <contexto>.

Devuelve un JSON con exactamente estos campos:
- "tendencia": 2 o 3 frases sobre cómo evoluciona la exposición, usando SOLO las cifras del contexto (CVEs KEV presentes, nuevos, SLA vencidos, MTTR, cumplimiento de SLA).
- "riesgos_principales": de 3 a 5 elementos; cada uno con "texto" (una frase), "cve_ids" (lista) y "activos" (lista) tomados únicamente del contexto.
- "recomendaciones": de 3 a 5 acciones concretas y priorizadas, derivadas de los riesgos y de los SLA vencidos.

Máximo 250 palabras en total. No inventes cifras, CVEs ni equipos.

<contexto>
{contexto}
</contexto>
