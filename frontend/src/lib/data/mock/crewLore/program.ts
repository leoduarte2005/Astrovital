import type { CastMember, ProgramMonth } from './types'

/** Lançamento fictício. Dia de missão 1 = 2026-10-05; dia 42 = 2026-11-15. */
export const LAUNCH_DATE = '2026-10-05'

export const CAST: CastMember[] = [
  { id: 'okafor', name: 'Cmdr. Adaeze Okafor', role: 'Comandante reserva', agency: 'NASA', hint: 'Veterana, ironiza o próprio perfeccionismo; treina em par com Silva.' },
  { id: 'lindqvist', name: 'Dr. Erik Lindqvist', role: 'Médico de voo reserva', agency: 'ESA', hint: 'Fala pouco e cozinha muito; rival amigável de Costa no xadrez de diagnósticos.' },
  { id: 'ramirez', name: 'Eng. Paula Ramírez', role: 'Engenheira de voo reserva', agency: 'NASA', hint: 'Competitiva na academia; primeiro atrito com Silva no treino de sobrevivência.' },
  { id: 'haddad', name: 'Capt. Samir Haddad', role: 'Astronauta de outra tripulação, CAPCOM nas simulações', agency: 'MBRSC', hint: 'Voz calma nos sims de atraso de comunicação; contador de histórias nas fogueiras.' },
  { id: 'kowalski', name: 'Maj. Tom Kowalski', role: 'Mentor veterano da ISS', agency: 'NASA', hint: 'Radioamador; leva Silva para o clube de rádio.' },
  { id: 'iyer', name: 'Dra. Priya Iyer', role: 'Psicóloga de saúde comportamental (BHP)', agency: 'NASA', hint: 'Conduz a mediação do mês 18 e as entrevistas de calibração.' },
  { id: 'walsh', name: 'Bryn Walsh', role: 'Líder de mergulho da NBL', agency: 'NASA', hint: 'Exigente; elogia pouco e de forma precisa.' },
  { id: 'beaumont', name: 'Claire Beaumont', role: 'Treinadora de força e reabilitação (ASCR)', agency: 'NASA', hint: 'Adapta programas a lesões antigas; não aceita "está tudo bem".' },
  { id: 'nguyen', name: 'Linh Nguyen', role: 'Coordenadora de simulações', agency: 'NASA', hint: 'Desenha as falhas dos sims; gosta de pegar a tripulação de surpresa.' },
]

export const PROGRAM: ProgramMonth[] = [
  { month: 1, period: '2024-10', phase: 'Integração', location: 'Houston (JSC)', summary: 'Anúncio da tripulação, mudança para Houston, primeiras aulas e o primeiro almoço juntos.' },
  { month: 2, period: '2024-11', phase: 'Sistemas', location: 'Houston (JSC)', summary: 'Fundamentos da nave e do suporte de vida (ECLSS), com provas semanais.' },
  { month: 3, period: '2024-12', phase: 'NBL', location: 'Houston (piscina NBL)', summary: 'Primeira certificação de EVA na piscina de flutuabilidade neutra.' },
  { month: 4, period: '2025-01', phase: 'Base física e médica', location: 'Houston (ASCR e clínica)', summary: 'Testes basais completos e programas individuais de força.' },
  { month: 5, period: '2025-02', phase: 'Centrífuga', location: 'Centrífuga humana', summary: 'Perfis de lançamento e reentrada até 6 G, com técnica anti-G.' },
  { month: 6, period: '2025-03', phase: 'Sobrevivência', location: 'Golfo do México e treino de frio', summary: 'Pouso na água, saída da cápsula e abrigo em clima frio.' },
  { month: 7, period: '2025-04', phase: 'Robótica', location: 'Houston (robotics bay)', summary: 'Operação do braço robótico e captura de carga.' },
  { month: 8, period: '2025-05', phase: 'Voo parabólico', location: 'Ellington Field', summary: 'Dois dias de parábolas: microgravidade real em blocos de 20 s.' },
  { month: 9, period: '2025-06', phase: 'Geologia de campo', location: 'Arizona', summary: 'Amostragem, descrição de afloramentos e noites de acampamento.' },
  { month: 10, period: '2025-07', phase: 'Isolamento', location: 'Análogo de habitat (30 dias)', summary: 'Trinta dias fechados com atraso de comunicação e sono restrito em parte do período.' },
  { month: 11, period: '2025-08', phase: 'Recuperação', location: 'Houston', summary: 'Descompressão, revisões pós-análogo e folgas curtas.' },
  { month: 12, period: '2025-09', phase: 'Meio do programa', location: 'Houston', summary: 'Avaliação de meio-termo e treino médico cruzado com Costa.' },
  { month: 13, period: '2025-10', phase: 'EVA avançada', location: 'Houston (piscina NBL)', summary: 'Corridas de 6 h na piscina; carga nos ombros e nas mãos.' },
  { month: 14, period: '2025-11', phase: 'Falhas de suporte de vida', location: 'Houston (câmara de testes)', summary: 'Vazamento, CO₂ alto e perda de água simulados em câmara.' },
  { month: 15, period: '2025-12', phase: 'Pausa e atraso de comunicação', location: 'Casa e Houston', summary: 'Folga de fim de ano e, na volta, sims com atraso de até 20 min.' },
  { month: 16, period: '2026-01', phase: 'Radiação', location: 'Houston', summary: 'Eventos de partículas solares e montagem do abrigo contra tempestade.' },
  { month: 17, period: '2026-02', phase: 'Simulação integrada', location: 'Houston (simulador)', summary: 'Setenta e duas horas contínuas de missão, com falhas encadeadas.' },
  { month: 18, period: '2026-03', phase: 'Coesão', location: 'Houston', summary: 'Atrito após uma decisão errada no sim e sessão de mediação com a BHP.' },
  { month: 19, period: '2026-04', phase: 'Emergências médicas', location: 'Houston (medbay)', summary: 'Ensaios de emergência com cada tripulante como paciente e como socorrista.' },
  { month: 20, period: '2026-05', phase: 'Calibração da IA', location: 'Houston', summary: 'Entrevistas de perfil, preferências e linha de base para o modelo individual.' },
  { month: 21, period: '2026-06', phase: 'Família e mídia', location: 'Houston', summary: 'Dia da família no galpão e agenda de entrevistas.' },
  { month: 22, period: '2026-07', phase: 'Simulações finais', location: 'Houston (simulador)', summary: 'Missões completas de ponta a ponta, sem aviso prévio de falhas.' },
  { month: 23, period: '2026-08', phase: 'Prontidão', location: 'Houston', summary: 'Revisões médicas e técnicas finais, assinatura de prontidão.' },
  { month: 24, period: '2026-09', phase: 'Quarentena e lançamento', location: 'Quarentena (HSP) e base de lançamento', summary: 'Programa de estabilização de saúde e lançamento em 5 de outubro.' },
]
