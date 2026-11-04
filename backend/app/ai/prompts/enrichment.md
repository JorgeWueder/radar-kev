Con la información de <contexto> redacta la descripción de un ticket de remediación para el equipo de seguridad.

Devuelve un JSON con exactamente estos campos:
- "resumen": 2 o 3 frases que expliquen qué es la vulnerabilidad (usa el nombre y la descripción de la ficha) y citen el CVE.
- "por_que_urgente": lista de 3 a 5 frases COMPLETAS, cada una con un dato concreto del contexto: que está en el catálogo KEV de CISA (explotación activa confirmada), el valor de EPSS, la criticidad del equipo afectado (cítalo por su nombre), la fecha límite de CISA y, si el contexto lo indica, el uso conocido en ransomware.
- "pasos_remediacion": lista de 2 a 5 pasos concretos basados SOLO en la "Acción requerida" y en las referencias del contexto. No agregues pasos que no estén respaldados por esas fuentes.

No escribas URLs dentro de los textos. No menciones ningún CVE ni equipo que no esté en el contexto.

<contexto>
{contexto}
</contexto>
