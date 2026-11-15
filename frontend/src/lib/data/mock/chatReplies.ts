/**
 * Mock assistant replies. Text that comes from the AI is not translated (see i18n.md),
 * so these stay in the source language of the mock.
 */
export const MOCK_ASSISTANT_REPLIES: readonly string[] = [
  'Obrigado por contar. Vou registrar isso no seu perfil. Você notou algum sintoma junto com essa sensação?',
  'Entendi. Seu sono recente ficou abaixo da média. Quer que eu compare com a sua baseline de descanso?',
  'Anotado. Se a sensação persistir por mais de um dia, vale conversar com o oficial médico. Eu não substituo um diagnóstico.',
  'Obrigado. Hoje a cabine está com CO2 dentro da faixa nominal. Quer ver o gráfico das últimas horas?',
  'Certo. Posso atualizar suas metas ou preferências quando quiser. Basta me dizer o que mudou.',
]

export function pickMockReply(): string {
  const index = Math.floor(Math.random() * MOCK_ASSISTANT_REPLIES.length)
  return MOCK_ASSISTANT_REPLIES[index] ?? MOCK_ASSISTANT_REPLIES[0] ?? ''
}
