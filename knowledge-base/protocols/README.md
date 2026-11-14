# knowledge-base/protocols/

**Responsável:** Selliny (M1) conteúdo. Renderização: Rafael (M3).

## Propósito
Tutoriais passo a passo de autoexame, servidos pela Central em `GET /api/protocols/{id}` e exibidos no painel.

## Protocolos obrigatórios
| ID | Exame | Resultado registrado (`SELF_EXAM`) |
| :--- | :--- | :--- |
| `capillary_blood` | Coleta de sangue capilar / glicemia na ponta do dedo | glicemia mg/dL, hemoglobina se disponível |
| `amsler_grid` | Grade de Amsler (teste interativo na tela) | olho, quadrantes distorcidos, escotomas |
| `ultrasound_onsd` | Ultrassom point-of-care (bainha do nervo óptico) | ONSD mm por olho |
| `blood_pressure` | Pressão arterial | sistólica/diastólica mmHg, posição |
| `temperature` | Temperatura | °C, local |

## Formato esperado por protocolo
`id`, `title`, `duration_s`, `materials[]`, `steps[]` (`text`, `image` local em `frontend/public/`, `timer_s`, `safety_note`), `result_schema`, `linked_risks[]`.

## Regras
- Linguagem curta e imperativa, um passo por tela.
- Imagens apenas locais.
