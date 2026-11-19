# Pruebas de carga con JMeter

Módulo crítico: **Resumen (dashboard)**. Cada usuario virtual repite: `GET /dashboard/kpis` → `GET /vulnerabilities?limit=50` → `GET /dashboard/top-assets`, con pausa de 1 a 3 s. Un único login previo (el login admite 5 por minuto por IP) y se reutiliza el token.

- Plan: `radar_carga.jmx` (abrir en la interfaz de JMeter para las capturas). Propiedades: `users`, `rampup`, `duration`, `host`, `port`.
- Ensayo: `.\jmeter\ensayo.ps1 -Users 140 -RampUp 20 -Duration 60` (deja `resultados/N<n>/informe/index.html` y añade una línea a `resultados/resumen.txt`).
- Equipo: 16 CPU lógicas, 8 GB para Docker; app en `localhost:8080`; un solo proceso uvicorn y pool de BD de 10 + 30.

## Ensayo y error (rampa 20 s, 60 s de carga)

| N usuarios | Muestras | Error | Prom. | p95 |
|---|---|---|---|---|
| 10 | 131 | 0 % | 36 ms | 50 ms |
| 50 | 1206 | 0 % | 60 ms | 154 ms |
| 100 | 1794 | 0 % | 760 ms | 1373 ms |
| 125 | 1778 | 0 % | 1525 ms | 2457 ms |
| 130 (backend recién reiniciado) | 1789 | 0 % | 1641 ms | 2624 ms |
| 135 | 1752 | 0 % | 1877 ms | 2824 ms |
| **140** (3 ejecuciones) | ~1800 | **0 %** | ~1860 ms | ~2900 ms |
| 145 (recién reiniciado) | 1603 | 9.05 % | 4439 ms | 30002 ms |
| 150 (recién reiniciado) | 1585 | 9.4 % | 4720 ms | 30002 ms |
| 160 (recién reiniciado) | 881 | 36.3 % | 11576 ms | 30004 ms |
| 175 (recién reiniciado) | 742 | 47.2 % | 14629 ms | 30005 ms |
| 200 | 839 | 47.7 % | 14793 ms | 30006 ms |

**N máximo con 0 % de error: 140 usuarios simultáneos.** (145 pasó una vez con el servidor "caliente" pero falló al reiniciar; no es estable.)

Cuello de botella: el pool de conexiones de SQLAlchemy (`QueuePool limit of size 10 overflow 30 reached`, `core/db/session.py`) y un solo proceso uvicorn; `/dashboard/kpis` es la consulta más pesada. El valor depende de esta máquina.
