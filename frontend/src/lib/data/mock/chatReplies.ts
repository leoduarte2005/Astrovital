import type { CrewContext, LearnedMonth } from '@/lib/model/crewContext'
import type { ChatReplyPayload, Escalation, TelemetryFramePayload } from '@/lib/model/live'

/**
 * Simulated assistant of the central. Every reply is built from the crew member's context (baseline, what the
 * AI learned in training, watch list, tone, how the person reports symptoms, what helps them recover) and the
 * current frame, in the shape of `CHAT_REPLY`. The assistant answers in English by default (rules/chat.md), the
 * language of the crew record, and the UI never translates it. No real AI and never a diagnosis.
 */

type Topic = 'sleep' | 'back' | 'headache' | 'stress' | 'heart' | 'pause' | 'general'

/** Words that point to a topic (en, pt, es), compared without accents and in lower case. */
const KEYWORDS: Record<Exclude<Topic, 'general'>, string[]> = {
  heart: ['coracao', 'palpit', 'peito', 'batimento', 'heart', 'chest', 'corazon', 'pecho'],
  headache: ['cabeca', 'cefale', 'enxaquec', 'tontur', 'headache', 'dizz', 'cabeza', 'mareo', 'co2', 'visao', 'vision'],
  back: ['lombar', 'costas', 'coluna', 'back', 'spine', 'espalda', 'lumbar'],
  sleep: ['sono', 'dormi', 'insonia', 'cansa', 'fadiga', 'exaust', 'sleep', 'tired', 'fatigue', 'sueno'],
  stress: ['estress', 'estres', 'ansie', 'ansio', 'triste', 'preocup', 'stress', 'anxi', 'sad', 'worr', 'humor', 'mood', 'sozinho', 'lonely'],
  pause: ['pausa', 'descans', 'musica', 'relax', 'break', 'music', '休息'],
}

/**
 * Words and phrases searched in the training memory and the watch list for each topic (the crew record is in
 * English). Matched at the start of a word only, so "rest" would match "restorative": the lists stay specific,
 * and back pain uses "lower back", never a bare "back" (which would match "backup").
 */
const MEMORY_WORDS: Record<Topic, string[]> = {
  heart: ['heart', 'cardio'],
  headache: ['headache', 'vision', 'sans'],
  back: ['lower back', 'lumbar', 'spine'],
  sleep: ['sleep', 'fatigue', 'tired'],
  stress: ['stress', 'withdraw', 'tension', 'command', 'anxiety', 'alone', 'conflict'],
  pause: ['music', 'piano', 'radio', 'chess', 'restorative'],
  general: [],
}

/**
 * Notes that are guidance for the assistant (consent, topics not to raise) are never quoted back to the crew
 * member: they can name people or private matters ("do not mention it without consent").
 */
const GUIDANCE_NOTE = /\b(consent|do not|unless)\b/i

const COUNTERMEASURES: Record<Topic, string[]> = {
  sleep: [
    "Log tonight's sleep (bedtime and wake-up time)",
    'Avoid bright screens in the last hour before sleep',
    'If the 3-night average drops below your baseline, review the schedule with the medical officer',
  ],
  back: [
    'Rate the pain from 0 to 10 after the next resistive exercise',
    'Do the core protocol before training',
    'If the pain spreads to the leg, tell the medical officer',
  ],
  headache: [
    'Drink water and check the module ventilation',
    "Compare with the last hours of CO2 in the lungs' charts",
    'If your vision changes, log it for SANS screening',
  ],
  stress: [
    'A 10-minute break away from the task',
    'Slow breathing for 3 minutes: 4 s in, 6 s out',
    'If you like, book a talk with behavioural health support (BHP)',
  ],
  heart: ['Sit down and repeat the reading in 5 minutes', 'With chest pain or shortness of breath, tell the medical officer now'],
  pause: [],
  general: ['Do the daily check-in (sleep, energy, mood)', 'Review your trends against your baseline'],
}

const SOURCES: Record<Topic, string[]> = {
  sleep: ['NASA HRP: sleep and circadian rhythm'],
  back: ['NASA HRP: injury and spine in microgravity'],
  headache: ['NASA HRP: cabin atmosphere (CO2)', 'NASA HRP: SANS'],
  stress: ['NASA HRP: behavioural health'],
  heart: ['NASA HRP: cardiovascular adaptation'],
  pause: ['NASA HRP: behavioural health'],
  general: [],
}

const DISCLAIMER = 'Simulated reply built from your context; it does not replace a medical assessment.'

/** Lower case without accents, for keyword matching. */
function plain(text: string): string {
  return text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
}

/** True when `text` has a word (or a phrase) that starts with one of `starts`. */
function mentions(text: string, starts: string[]): boolean {
  const words = ` ${plain(text).replace(/[^a-z0-9]+/g, ' ')}`
  return starts.some((start) => words.includes(` ${start}`))
}

function topicOf(text: string): Topic {
  const words = plain(text)
  for (const [topic, keys] of Object.entries(KEYWORDS) as [Exclude<Topic, 'general'>, string[]][]) {
    if (keys.some((key) => words.includes(key))) return topic
  }
  return 'general'
}

const number = (value: number, decimals = 0) =>
  new Intl.NumberFormat('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(value)

/** "HR 59 bpm: 9% above your baseline (54 bpm)". */
function versusBaseline(label: string, now: number, base: number, unit: string, decimals = 0): string {
  const change = Math.round(((now - base) / base) * 100)
  const where = change === 0 ? 'equal to' : change > 0 ? `${change}% above` : `${-change}% below`
  return `${label} ${number(now, decimals)} ${unit}: ${where} your baseline (${number(base, decimals)} ${unit})`
}

function evidenceFor(topic: Topic, context: CrewContext, frame: TelemetryFramePayload): string[] {
  const { vitals, environment } = frame
  const base = context.baseline
  const hr = versusBaseline('HR', vitals.heart_rate_bpm, base.hrBpm, 'bpm')
  // HRV and respiration depend on the AI: absent (0) while it is not ready, so they are not cited then.
  const hrv = frame.ai_ready ? versusBaseline('HRV', vitals.hrv_ms, base.hrvMs, 'ms') : null
  const resp = frame.ai_ready ? versusBaseline('Respiration', vitals.resp_rate_bpm, base.respBpm, 'rpm', 1) : null
  const spo2 = `SpO2 ${number(vitals.spo2_pct, 1)} %`
  const lastMonth = context.wellbeing.at(-1)
  const sleep = lastMonth
    ? `Average sleep in the last training month (${lastMonth.period}): ${number(lastMonth.sleepH, 1)} h; baseline ${number(base.sleepH, 1)} h`
    : null
  const co2 = `Cabin CO2 ${number(environment.co2_ppm)} ppm`
  // Posture is a text from the central: quoted as it came.
  const posture = vitals.posture ? `Current posture (RF sensing): ${vitals.posture}` : null

  const byTopic: Record<Topic, (string | null)[]> = {
    sleep: [hrv, hr, sleep],
    back: [posture, hrv],
    headache: [co2, spo2, resp],
    stress: [hrv, hr, resp],
    heart: [hr, hrv, spo2],
    pause: [hrv, hr],
    general: [hr, hrv, spo2],
  }
  return byTopic[topic].filter((line): line is string => line !== null)
}

/** The most recent training month whose notes mention the topic. */
function memoryFor(topic: Topic, learned: LearnedMonth[]): { month: LearnedMonth; note: string } | null {
  const words = MEMORY_WORDS[topic]
  if (words.length === 0) return null
  for (let i = learned.length - 1; i >= 0; i--) {
    const month = learned[i]
    const note = month?.notes.find((text) => !GUIDANCE_NOTE.test(text) && mentions(text, words))
    if (month && note) return { month, note }
  }
  return null
}

function opening(context: CrewContext, topic: Topic): string {
  if (topic === 'general') return 'Hello.'
  if (context.tone === 'technical') return 'Logged.'
  if (context.tone === 'direct') return 'Understood.'
  return 'Thank you for telling me.'
}

/** The closing question follows how the person tends to report (assistant guidance, never shown as such). */
function question(context: CrewContext, topic: Topic): string {
  const style = plain(context.assistant.reportingStyle)
  if (topic === 'general') return 'How are you feeling today?'
  if (topic === 'pause') return 'Shall I schedule it for after your next work block?'
  if (style.includes('under-report')) return 'On a scale from 0 to 10, how is it now? Even if it seems small, the number helps me compare.'
  if (style.includes('does not report') || style.includes('objectively')) return 'Direct question: when did it start, and what makes it worse?'
  if (style.includes('clinical precision')) return 'Leave the analysis to me: here you are a patient too. When did you first notice it?'
  return 'When did you first notice it?'
}

/** What helps this person recover, from the crew record. */
function comfortLine(context: CrewContext): string | null {
  const activity = context.comfort.activities[0]
  const music = context.comfort.music[0]
  if (!activity && !music) return null
  if (activity && music) return `A short break may help: ${activity}, or listening to ${music}.`
  return `A short break may help: ${activity ?? music}.`
}

/** A reply in the shape of the central's `CHAT_REPLY`, built from the crew context and the current frame. */
export function mockReply(text: string, context: CrewContext, frame: TelemetryFramePayload): ChatReplyPayload {
  const topic = topicOf(text)
  const memory = memoryFor(topic, context.learned)
  const words = MEMORY_WORDS[topic]
  const watched = words.length > 0 ? context.watchlist.find((item) => mentions(item, words)) : undefined
  const comfort = topic === 'pause' || topic === 'stress' ? comfortLine(context) : null
  const urgent = topic === 'heart' && /peito|chest|pecho|falta de ar|breath/.test(plain(text))

  const lines = [
    opening(context, topic),
    urgent ? 'Chest pain needs an in-person assessment: tell the medical officer now. I have flagged this conversation to the crew.' : null,
    topic === 'general' ? 'Your current readings, compared with your own baseline, are below.' : null,
    memory
      ? `From your training, month ${memory.month.month} (${memory.month.period}, ${memory.month.phase}), I noted: "${memory.note}"`
      : null,
    watched ? `This is on the list I watch closely for you: ${watched}.` : null,
    comfort,
    question(context, topic),
  ]

  const escalation: Escalation = urgent ? 'CREW' : 'LOCAL'
  const countermeasures = topic === 'pause' ? [comfortLine(context) ?? ''].filter(Boolean) : COUNTERMEASURES[topic]
  const sources = [
    ...SOURCES[topic],
    `individual baseline ${context.crewId} (730 training days)`,
    ...(memory ? [`training memory M${String(memory.month.month).padStart(2, '0')}`] : []),
  ]

  return {
    text: lines.filter((line): line is string => line !== null).join(' '),
    evidence: evidenceFor(topic, context, frame),
    countermeasures,
    source_ids: sources,
    escalation,
    disclaimer: DISCLAIMER,
  }
}
