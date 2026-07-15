# Agente de IA en Python — Reto DataQuantum

**Autor:** Jordi · **Periodo:** 15/07 → ~14/08/2026 · **Estado:** Fase 0 (esqueleto del repo)

Agente de IA ejecutado desde la terminal, construido de forma incremental en 4 niveles:
chat simple contra un LLM (**Básico**) → conversación con memoria (**Intermedio**) →
uso de herramientas vía tool calling (**Avanzado**) → proyecto completo sobre un caso
de uso real (**Experto**). El objetivo es formativo: comprender cada pieza de un agente
antes de usar abstracciones.

## Puesta en marcha

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env         # y rellenar las claves API
```

> Todavía no hay código ejecutable — llega con el Nivel Básico (Fase 2).

## Documentación

| Documento | Qué contiene |
|---|---|
| [docs/diario_decisiones.md](docs/diario_decisiones.md) | ⭐ Tabla oficial de decisiones técnicas con fecha |
| [docs/E1_Especificacion_Requisitos.md](docs/E1_Especificacion_Requisitos.md) | Requisitos, alcance y riesgos |
| [docs/E2_Arquitectura.md](docs/E2_Arquitectura.md) | Arquitectura y diagrama global |
| [docs/E3_Estado_Arte_Planificacion.md](docs/E3_Estado_Arte_Planificacion.md) | Estado del arte y planificación por fases |
| [docs/E4_Entrega_Final.md](docs/E4_Entrega_Final.md) | Entrega final (se redacta al cierre) |
| [docs/ADR/](docs/ADR/) | Decisiones de arquitectura (ADRs) |

## Normas del proyecto

1. **Ninguna decisión sin fila fechada** en el diario de decisiones.
2. **Toda utilidad sin IA tiene tests** (norma activa desde el Nivel Intermedio).
3. **Toda excepción queda registrada** en `logs/`.
4. Los secretos viven en `.env` (gitignored); el repo solo contiene `.env.example`.

## Git

Ramas `feature/*` → `main`, con un tag por nivel completado:
`nivel-basico` · `nivel-intermedio` · `nivel-avanzado` · `nivel-experto`.
