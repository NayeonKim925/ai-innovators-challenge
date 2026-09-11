# Architecture

```text
Dataset adapter -> runtime incident contract -> deterministic analysis tools
                                                |              |
                                                v              v
                                          evidence assembly <- workflow state
                                                |
                                                v
                                   API -> reviewable report -> human decision log
```

## Backend boundaries

- `domain`: validated contracts shared by API, tools, and workflow
- `data`: dataset-specific adapters and runtime-only repositories
- `analytics`: deterministic anomaly and root-cause ranking tools
- `workflows`: LangGraph orchestration; no raw numerical calculation or equipment control
- `api`: HTTP validation and serialization only
- `evals`: benchmark-only code that can read evaluation truth

## Initial endpoints

- `GET /api/health`
- `GET /api/datasets`
- `GET /api/incidents`
- `GET /api/incidents/{incident_id}`
- `POST /api/incidents/{incident_id}/investigations`

Human review persistence and the React investigation UI are the next implementation
milestone after causRCA data preparation and deterministic benchmark integration.
