export type LabStatus = 'active' | 'fallback'

export interface LabMeta {
  key: string
  label: string
  aliases: string[]
  markPath?: string
  markDarkPath?: string
  markTilePath?: string
  color: string
  colorDark: string
  status: LabStatus
  searchTerms: string[]
}

const UNKNOWN_COLORS = [
  '#8b5cf6',
  '#06b6d4',
  '#10b981',
  '#f59e0b',
  '#ef4444',
  '#ec4899',
  '#6366f1',
  '#14b8a6',
  '#f97316',
  '#84cc16',
]

const LAB_DEFINITIONS = [
  ['nvidia', 'NVIDIA', ['Nvidia'], '#76b900', ['gpu', 'cuda', 'nemotron']],
  ['alibaba', 'Alibaba', ['Alibaba Cloud', 'Qwen'], '#ff6a00', ['dashscope', 'tongyi', 'qwen']],
  ['openai', 'OpenAI', ['ChatGPT'], '#10a37f', ['gpt', 'o-series', 'chatgpt']],
  ['mistral', 'Mistral AI', ['Mistral'], '#fd6f00', ['mixtral', 'ministral', 'le chat']],
  ['anthropic', 'Anthropic', ['Claude'], '#d97757', ['claude', 'constitutional ai']],
  ['google', 'Google', ['Google DeepMind', 'DeepMind'], '#4285f4', ['gemini', 'gemma', 'bard']],
  ['cohere', 'Cohere', ['Command'], '#39594d', ['command', 'aya', 'embed']],
  ['zai', 'Z.ai', ['Z AI', 'Zhipu AI'], '#2563eb', ['glm', 'chatglm']],
  ['zhipuai', 'Zhipu AI', ['Zhipu', '智谱AI', '智谱'], '#c026d3', ['glm', 'chatglm', 'bigmodel']],
  ['moonshotai', 'Moonshot AI', ['Moonshot', 'Kimi'], '#16a34a', ['kimi', 'moonshot']],
  ['xai', 'xAI', ['X.AI', 'Grok'], '#111111', ['grok', 'x']],
  ['llama', 'Meta Llama', ['Llama', 'Meta'], '#0668e1', ['meta ai', 'llama']],
  ['minimax', 'MiniMax', ['MiniMax AI'], '#f97316', ['abab', 'hailuo']],
  ['inceptron', 'Inceptron', [], '#0ea5e9', ['mercury']],
  ['xiaomi', 'Xiaomi', ['Mi'], '#ff6900', ['mimo', 'mi']],
  ['stepfun', 'StepFun', ['Step Fun', '阶跃星辰'], '#7c3aed', ['step', 'step-2']],
  ['deepseek', 'DeepSeek', [], '#4d6bfe', ['deepseek', 'r1', 'v3']],
  ['perplexity', 'Perplexity', ['Perplexity AI'], '#20b8cd', ['sonar', 'search']],
  ['sakana', 'Sakana AI', ['Sakana'], '#0f766e', ['evolutionary', 'japanese ai']],
  ['upstage', 'Upstage', [], '#ff4f00', ['solar']],
  ['nova', 'Amazon Nova', ['Nova', 'AWS Nova', 'Amazon'], '#ff9900', ['aws', 'amazon bedrock']],
  ['poolside', 'Poolside', [], '#e11d48', ['code', 'programming']],
  ['sarvam', 'Sarvam AI', ['Sarvam'], '#22c55e', ['india', 'indic']],
] as const satisfies ReadonlyArray<
  readonly [key: string, label: string, aliases: readonly string[], color: string, searchTerms: readonly string[]]
>

function normalizeDev(dev: string | null | undefined): string {
  return String(dev ?? '').trim().toLowerCase()
}

function uniqueValues(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values) {
    const normalized = String(value ?? '').trim()
    const key = normalized.toLowerCase()
    if (!normalized || seen.has(key)) continue
    seen.add(key)
    result.push(normalized)
  }
  return result
}

function hashString(value: string): number {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0
  }
  return hash
}

function fallbackColor(dev: string | null | undefined): string {
  const key = normalizeDev(dev)
  if (!key) return '#8b95a5'
  return UNKNOWN_COLORS[hashString(key) % UNKNOWN_COLORS.length]
}

function fallbackLabel(dev: string | null | undefined, devName?: string | null): string {
  const explicitName = String(devName ?? '').trim()
  if (explicitName) return explicitName

  const key = String(dev ?? '').trim()
  if (!key) return 'Unknown lab'

  return key
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function darkColor(color: string): string {
  return color === '#111111' ? '#9ca3af' : color
}

export const LABS: Record<string, LabMeta> = Object.fromEntries(
  LAB_DEFINITIONS.map(([key, label, aliases, color, searchTerms]) => [
    key,
    {
      key,
      label,
      aliases: [...aliases],
      markPath: `/assets/labs/${key}/mark.svg`,
      markDarkPath: `/assets/labs/${key}/mark-dark.svg`,
      markTilePath: `/assets/labs/${key}/mark-tile.svg`,
      color,
      colorDark: darkColor(color),
      status: 'active',
      searchTerms: uniqueValues([key, label, ...aliases, ...searchTerms]),
    },
  ]),
)

export const LAB_KEYS = LAB_DEFINITIONS.map(([key]) => key)

const LAB_ALIAS_KEYS: Record<string, string> = {}
for (const [key, label, aliases] of LAB_DEFINITIONS) {
  for (const alias of uniqueValues([label, ...aliases])) {
    const aliasKey = normalizeDev(alias)
    if (aliasKey && aliasKey !== key) LAB_ALIAS_KEYS[aliasKey] = key
  }
}

export function getLabMeta(dev: string | null | undefined, devName?: string | null): LabMeta {
  const key = normalizeDev(dev)
  const aliasKey = LAB_ALIAS_KEYS[key]
  const known = LABS[key] ?? (aliasKey ? LABS[aliasKey] : undefined)
  if (known) return known

  const label = fallbackLabel(dev, devName)
  const color = fallbackColor(dev)
  return {
    key,
    label,
    aliases: devName && devName !== label ? [devName] : [],
    color,
    colorDark: color,
    status: 'fallback',
    searchTerms: uniqueValues([key, label, devName]),
  }
}

export function labLabel(dev: string | null | undefined, devName?: string | null): string {
  return getLabMeta(dev, devName).label
}

export function labColorFor(dev: string | null | undefined): string {
  return getLabMeta(dev).color
}

export function labColorForDark(dev: string | null | undefined): string {
  return getLabMeta(dev).colorDark
}

export function labSearchValues(dev: string | null | undefined, devName?: string | null): string[] {
  const meta = getLabMeta(dev, devName)
  return uniqueValues([meta.key, meta.label, devName, ...meta.aliases, ...meta.searchTerms])
}
