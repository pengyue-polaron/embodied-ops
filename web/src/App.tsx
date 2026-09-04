import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Activity,
  Camera,
  ChevronDown,
  ChevronUp,
  CircleStop,
  Database,
  Play,
  RefreshCw,
  SquareTerminal,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

type Json = Record<string, unknown>
type Option = { value: string; label: string; depends_value?: string }
type Field = {
  name: string
  label: string
  type: "text" | "select" | "combobox" | "checkbox"
  required?: boolean
  default?: string | boolean
  placeholder?: string
  help_text?: string
  options?: Option[]
  depends_on?: string
  derive_from?: string
  transform?: "snake_case"
}
type FormDefinition = {
  id: string
  label: string
  eyebrow: string
  title: string
  submit_label: string
  description?: string
  tone?: "default" | "danger"
  confirm?: string
  fields: Field[]
}
type CameraDefinition = { id: string; label: string; url?: string; port?: number; path?: string }
type CameraControl = {
  label: string
  workflow: string
  values: Json
  tone?: "default" | "danger"
  confirm?: string
}
type ConfigurationType = {
  id: string
  label: string
  extension: string
  language: string
  templates: Option[]
}
type Catalog = {
  product: { brand: string; title: string }
  cameras: CameraDefinition[]
  camera_controls: CameraControl[]
  workflows: FormDefinition[]
  registrations: FormDefinition[]
  configuration_types: ConfigurationType[]
  configuration_groups: { label: string; items: Option[] }[]
}
type InputAction = { id: string; label: string; tone: "default" | "primary" | "danger" | "quiet" }
type Progress = {
  id: string
  label: string
  current: number
  total: number | null
  phase: string
  detail: string
}
type WorkflowStatus = {
  schema_version: number
  revision: number
  run_id: string
  state: string
  active: boolean
  workflow: string
  name: string
  command: string[]
  started_at: string
  exit_code: number | null
  progress: Progress[]
  status_line: string
  input_revision: number
  input_phase: string
  input_detail: string
  input_actions: InputAction[]
  logs: string[]
}
type CameraStreamHealth = {
  ready: boolean
  fresh: boolean
  preview_fps: number | null
  age_s: number | null
  error: string | null
}
type CameraHealth = {
  available: boolean
  ok: boolean
  reason?: string
  streams: Record<string, CameraStreamHealth>
}

const EMPTY_STATUS: WorkflowStatus = {
  schema_version: 2,
  revision: 0,
  run_id: "",
  state: "idle",
  active: false,
  workflow: "",
  name: "",
  command: [],
  started_at: "",
  exit_code: null,
  progress: [],
  status_line: "",
  input_revision: 0,
  input_phase: "",
  input_detail: "",
  input_actions: [],
  logs: [],
}
const TOKEN = document.querySelector<HTMLMetaElement>('meta[name="operator-panel-token"]')?.content ?? ""

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { cache: "no-store", ...options })
  const payload = (await response.json()) as T & { error?: string }
  if (!response.ok) throw new Error(payload.error || `Request failed: ${response.status}`)
  return payload
}

function post<T>(path: string, payload: Json): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Operator-Panel-Token": TOKEN },
    body: JSON.stringify(payload),
  })
}

export function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [status, setStatus] = useState<WorkflowStatus>(EMPTY_STATUS)
  const [connected, setConnected] = useState(true)
  const [cameraHealth, setCameraHealth] = useState<CameraHealth | null>(null)
  const [cameraCollapsed, setCameraCollapsed] = useState(
    () => window.localStorage.getItem("operator-panel.camera-preview-collapsed") === "1",
  )
  const [cameraEpoch, setCameraEpoch] = useState(Date.now())
  const [activeTab, setActiveTab] = useState("")
  const [prefill, setPrefill] = useState<Record<string, Json>>({})
  const [notice, setNotice] = useState("")
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({})

  const showNotice = useCallback((message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice((current) => (current === message ? "" : current)), 3200)
  }, [])

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await request<WorkflowStatus>("/api/status"))
      setConnected(true)
    } catch {
      setConnected(false)
    }
  }, [])

  const refreshCameraHealth = useCallback(async () => {
    if (!catalog?.cameras.length) return
    try {
      setCameraHealth(await request<CameraHealth>("/api/camera-health"))
    } catch {
      setCameraHealth({ available: false, ok: false, streams: {}, reason: "Camera health unavailable" })
    }
  }, [catalog])

  useEffect(() => {
    request<Catalog>("/api/catalog")
      .then((next) => {
        setCatalog(next)
        setActiveTab(next.workflows[0]?.id || next.registrations[0]?.id || (next.configuration_types.length ? "configuration" : ""))
        document.title = `${next.product.brand} ${next.product.title}`
      })
      .catch((error: Error) => showNotice(error.message))
    void refreshStatus()
  }, [refreshStatus, showNotice])

  useEffect(() => {
    const timer = window.setInterval(refreshStatus, 800)
    return () => window.clearInterval(timer)
  }, [refreshStatus])

  useEffect(() => {
    void refreshCameraHealth()
    const timer = window.setInterval(refreshCameraHealth, 2000)
    return () => window.clearInterval(timer)
  }, [refreshCameraHealth])

  useEffect(() => {
    window.localStorage.setItem("operator-panel.camera-preview-collapsed", cameraCollapsed ? "1" : "0")
  }, [cameraCollapsed])

  useEffect(() => {
    tabRefs.current[activeTab]?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" })
  }, [activeTab])

  const startWorkflow = useCallback(
    async (workflow: string, values: Json) => {
      const next = await post<WorkflowStatus>("/api/start", { workflow, values })
      setStatus(next)
      setActiveTab(workflow)
    },
    [],
  )

  const register = useCallback(
    async (registration: string, values: Json) => {
      const result = await post<{
        created: string
        catalog: Catalog
        activate?: { panel: string; values: Json }
      }>("/api/register", { registration, values })
      setCatalog(result.catalog)
      if (result.activate) {
        setActiveTab(result.activate.panel)
        setPrefill((current) => ({ ...current, [result.activate!.panel]: result.activate!.values }))
      }
      showNotice(`Registered: ${result.created}`)
    },
    [showNotice],
  )

  const runCameraControl = async (control: CameraControl) => {
    if (control.confirm && !window.confirm(control.confirm)) return
    try {
      await startWorkflow(control.workflow, control.values)
      window.setTimeout(() => setCameraEpoch(Date.now()), 1000)
    } catch (error) {
      showNotice((error as Error).message)
    }
  }

  if (!catalog) {
    return (
      <div className="grid min-h-screen place-items-center bg-background">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <RefreshCw className="h-4 w-4 animate-spin" /> Loading operator catalog
        </div>
        {notice && <Toast message={notice} />}
      </div>
    )
  }

  const forms = [
    ...catalog.workflows.map((form) => ({ form, operation: "workflow" as const })),
    ...catalog.registrations.map((form) => ({ form, operation: "registration" as const })),
  ]

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1680px] items-center justify-between px-4 lg:px-6">
          <div className="flex items-baseline gap-3">
            <span className="text-[11px] font-semibold tracking-[0.22em] text-muted-foreground">{catalog.product.brand}</span>
            <h1 className="text-xl font-semibold tracking-tight">{catalog.product.title}</h1>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={status.active ? "default" : "outline"} className="gap-1.5">
              <Activity className="h-3 w-3" />
              {!connected ? "Disconnected" : status.active ? "Running" : "Idle"}
            </Badge>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-[1680px] gap-4 p-4 lg:p-6">
        {catalog.cameras.length > 0 && (
          <CameraDeck
            cameras={catalog.cameras}
            controls={catalog.camera_controls}
            health={cameraHealth}
            collapsed={cameraCollapsed}
            epoch={cameraEpoch}
            busy={status.active}
            onToggle={() => setCameraCollapsed((value) => !value)}
            onRefresh={() => setCameraEpoch(Date.now())}
            onControl={runCameraControl}
          />
        )}

        <Tabs value={activeTab} onValueChange={setActiveTab} className="min-w-0 animate-reveal">
          <TabsList
            aria-label="Operator sections"
            className="operator-tabs-list flex h-12 w-full snap-x snap-mandatory items-stretch justify-start overflow-x-auto rounded-none border-x-0 border-b bg-transparent p-0 sm:inline-flex sm:h-10 sm:w-fit sm:snap-none sm:items-center sm:rounded-lg sm:border sm:bg-card sm:p-1"
          >
            {forms.map(({ form }) => (
              <TabsTrigger
                key={form.id}
                value={form.id}
                ref={(element) => {
                  tabRefs.current[form.id] = element
                }}
                title={form.label}
                className="group relative h-12 min-w-[7.25rem] max-w-[15rem] shrink-0 snap-start justify-center rounded-none border-b-2 border-transparent px-3 text-xs font-medium text-muted-foreground transition-colors data-[state=active]:border-foreground data-[state=active]:bg-transparent data-[state=active]:text-foreground sm:h-8 sm:min-w-0 sm:max-w-none sm:rounded-sm sm:border-0 sm:data-[state=active]:bg-background sm:data-[state=active]:shadow-sm"
              >
                <span className="truncate">{form.label}</span>
              </TabsTrigger>
            ))}
            {catalog.configuration_types.length > 0 && (
              <TabsTrigger
                value="configuration"
                ref={(element) => {
                  tabRefs.current.configuration = element
                }}
                title="Configurations"
                className="group relative h-12 min-w-[7.25rem] shrink-0 snap-start justify-center rounded-none border-b-2 border-transparent px-3 text-xs font-medium text-muted-foreground transition-colors data-[state=active]:border-foreground data-[state=active]:bg-transparent data-[state=active]:text-foreground sm:h-8 sm:min-w-0 sm:rounded-sm sm:border-0 sm:data-[state=active]:bg-background sm:data-[state=active]:shadow-sm"
              >
                <span className="truncate">Configurations</span>
              </TabsTrigger>
            )}
          </TabsList>

          <div className="mt-3 grid min-w-0 gap-3 xl:grid-cols-[minmax(340px,0.72fr)_minmax(520px,1.28fr)]">
            <div className="min-w-0">
              {forms.map(({ form, operation }) => (
                <TabsContent key={form.id} value={form.id} className="m-0">
                  <WorkflowForm
                    definition={form}
                    initialValues={prefill[form.id]}
                    disabled={status.active}
                    onSubmit={async (values) => {
                      try {
                        if (form.confirm && !window.confirm(form.confirm)) return
                        if (operation === "registration") await register(form.id, values)
                        else await startWorkflow(form.id, values)
                      } catch (error) {
                        showNotice((error as Error).message)
                      }
                    }}
                  />
                </TabsContent>
              ))}
              {catalog.configuration_types.length > 0 && (
                <TabsContent value="configuration" className="m-0">
                  <ConfigurationEditor
                    types={catalog.configuration_types}
                    disabled={status.active}
                    onCatalog={setCatalog}
                    notify={showNotice}
                  />
                </TabsContent>
              )}
            </div>

            <SessionCard status={status} notify={showNotice} onStatus={setStatus} />
          </div>
        </Tabs>

        {catalog.configuration_groups.length > 0 && (
          <ConfigurationInventory groups={catalog.configuration_groups} />
        )}
      </main>
      {notice && <Toast message={notice} />}
    </div>
  )
}

function CameraDeck({
  cameras,
  controls,
  health,
  collapsed,
  epoch,
  busy,
  onToggle,
  onRefresh,
  onControl,
}: {
  cameras: CameraDefinition[]
  controls: CameraControl[]
  health: CameraHealth | null
  collapsed: boolean
  epoch: number
  busy: boolean
  onToggle: () => void
  onRefresh: () => void
  onControl: (control: CameraControl) => void
}) {
  const live = cameras.filter((camera) => health?.streams[camera.id]?.fresh).length
  return (
    <Card className="animate-reveal overflow-hidden">
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b px-4 py-3">
        <div>
          <CardTitle className="flex items-center gap-2 text-sm"><Camera className="h-4 w-4" /> Live cameras</CardTitle>
          <CardDescription className="mt-1 text-xs">
            {!health ? "Checking monitor" : !health.available ? health.reason || "Monitor offline" : `${live}/${cameras.length} live · read-only`}
          </CardDescription>
        </div>
        <div className="flex flex-wrap justify-end gap-1.5">
          <Button variant="ghost" size="sm" onClick={onRefresh}><RefreshCw className="h-3.5 w-3.5" /> Refresh</Button>
          <Button variant="ghost" size="sm" onClick={onToggle}>
            {collapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
            {collapsed ? "Show" : "Collapse"}
          </Button>
          {controls.map((control) => (
            <Button
              key={`${control.workflow}-${control.label}`}
              variant={control.tone === "danger" ? "destructive" : "outline"}
              size="sm"
              disabled={busy}
              onClick={() => onControl(control)}
            >
              {control.label}
            </Button>
          ))}
        </div>
      </CardHeader>
      {!collapsed && (
        <CardContent className={cn("grid gap-px bg-border p-0", cameraGridColumns(cameras.length))}>
          {cameras.map((camera) => {
            const stream = health?.streams[camera.id]
            const state = cameraState(health, stream)
            return (
              <figure key={camera.id} className="group relative min-h-32 overflow-hidden bg-black sm:min-h-44 xl:min-h-52">
                <img
                  src={`${cameraUrl(camera)}?panel_refresh=${epoch}`}
                  alt={`${camera.label} camera stream`}
                  className="h-full max-h-64 w-full object-contain"
                />
                <figcaption className="absolute inset-x-2 bottom-2 flex items-center justify-between gap-2 rounded-md border border-white/20 bg-black/80 px-2.5 py-1.5 text-white backdrop-blur">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.12em]">{camera.label}</span>
                  <span className="text-[10px] text-white/70">{state}</span>
                </figcaption>
              </figure>
            )
          })}
        </CardContent>
      )}
    </Card>
  )
}

function cameraGridColumns(count: number): string {
  if (count <= 1) return "grid-cols-1"
  if (count === 2) return "grid-cols-2"
  if (count === 3) return "grid-cols-2 xl:grid-cols-3"
  return "grid-cols-2 xl:grid-cols-4"
}

function WorkflowForm({
  definition,
  initialValues,
  disabled,
  onSubmit,
}: {
  definition: FormDefinition
  initialValues?: Json
  disabled: boolean
  onSubmit: (values: Json) => Promise<void>
}) {
  const defaults = useMemo(
    () => Object.fromEntries(definition.fields.map((field) => [field.name, field.default ?? (field.type === "checkbox" ? false : "")])),
    [definition],
  )
  const [values, setValues] = useState<Json>({ ...defaults, ...initialValues })
  const [submitting, setSubmitting] = useState(false)
  const derived = useRef<Record<string, string>>({})

  useEffect(() => setValues({ ...defaults, ...initialValues }), [defaults, initialValues])

  useEffect(() => {
    setValues((current) => {
      const next = { ...current }
      let changed = false
      for (const field of definition.fields.filter((candidate) => candidate.type === "select")) {
        const options = filteredOptions(field, next)
        const value = String(next[field.name] ?? "")
        if (!options.some((option) => option.value === value) && options.length) {
          next[field.name] = options[0].value
          changed = true
        }
      }
      return changed ? next : current
    })
  }, [definition, values])

  const change = (name: string, value: string | boolean) => {
    setValues((current) => {
      const next = { ...current, [name]: value }
      for (const target of definition.fields.filter((field) => field.derive_from === name)) {
        const previous = String(current[target.name] ?? "")
        if (previous && previous !== derived.current[target.name]) continue
        const generated = target.transform === "snake_case" ? snakeCase(String(value)) : String(value)
        next[target.name] = generated
        derived.current[target.name] = generated
      }
      return next
    })
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    try {
      await onSubmit(values)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card className="min-h-[430px]">
      <CardHeader className="border-b p-5">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">{definition.eyebrow}</p>
        <CardTitle className="text-xl">{definition.title}</CardTitle>
        {definition.description && <CardDescription>{definition.description}</CardDescription>}
      </CardHeader>
      <CardContent className="p-5">
        <form className="grid gap-4" onSubmit={submit}>
          {definition.fields.map((field) => (
            <FieldControl
              key={field.name}
              field={field}
              values={values}
              value={values[field.name]}
              disabled={disabled || submitting}
              onChange={(value) => change(field.name, value)}
            />
          ))}
          <Button
            className="mt-1 w-full"
            variant={definition.tone === "danger" ? "destructive" : "default"}
            disabled={disabled || submitting}
          >
            <Play className="h-4 w-4" /> {submitting ? "Starting…" : definition.submit_label}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

function FieldControl({
  field,
  values,
  value,
  disabled,
  onChange,
}: {
  field: Field
  values: Json
  value: unknown
  disabled: boolean
  onChange: (value: string | boolean) => void
}) {
  if (field.type === "checkbox") {
    return (
      <Label className="flex items-center gap-2 rounded-md border p-3 text-sm">
        <input
          type="checkbox"
          checked={Boolean(value)}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
          className="h-4 w-4 accent-black"
        />
        {field.label}
      </Label>
    )
  }
  const options = filteredOptions(field, values)
  const id = `field-${field.name}`
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{field.label}</Label>
      {field.type === "select" ? (
        <select
          id={id}
          value={String(value ?? "")}
          required={field.required !== false}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        >
          {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      ) : (
        <>
          <Input
            id={id}
            list={field.type === "combobox" ? `${id}-options` : undefined}
            value={String(value ?? "")}
            required={field.required !== false}
            disabled={disabled}
            placeholder={field.placeholder}
            onChange={(event) => onChange(event.target.value)}
          />
          {field.type === "combobox" && (
            <datalist id={`${id}-options`}>
              {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </datalist>
          )}
        </>
      )}
      {field.help_text && <p className="text-[11px] leading-relaxed text-muted-foreground">{field.help_text}</p>}
    </div>
  )
}

function SessionCard({
  status,
  notify,
  onStatus,
}: {
  status: WorkflowStatus
  notify: (message: string) => void
  onStatus: (status: WorkflowStatus) => void
}) {
  const sendInput = async (action: InputAction) => {
    try {
      onStatus(await post<WorkflowStatus>("/api/input", {
        action: action.id,
        run_id: status.run_id,
        input_revision: status.input_revision,
      }))
    } catch (error) {
      notify((error as Error).message)
    }
  }
  const stop = async () => {
    if (!window.confirm("Interrupt the active workflow and let it run cleanup?")) return
    try {
      onStatus(await post<WorkflowStatus>("/api/stop", { run_id: status.run_id }))
    } catch (error) {
      notify((error as Error).message)
    }
  }

  return (
    <Card className="flex min-h-[430px] min-w-0 flex-col">
      <CardHeader className="flex-row items-start justify-between space-y-0 border-b p-4">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">SESSION</p>
          <CardTitle className="mt-1 truncate text-base">{status.name || "No active workflow"}</CardTitle>
          <CardDescription className="mt-1 text-xs">
            {!status.active
              ? "Start a workflow to inspect its output."
              : status.input_actions.length
                ? [status.input_phase || "Waiting for your decision", status.input_detail].filter(Boolean).join(" · ")
                : "Running; actions appear only at guarded input points."}
          </CardDescription>
        </div>
        <Button variant="destructive" size="sm" disabled={!status.active} onClick={stop}>
          <CircleStop className="h-3.5 w-3.5" /> Stop
        </Button>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-3 p-4">
        <ProgressPanel status={status} />
        <div className="flex min-h-8 flex-wrap gap-2">
          {status.input_actions.map((action) => (
            <Button
              key={action.id}
              size="sm"
              variant={action.tone === "danger" ? "destructive" : action.tone === "quiet" ? "ghost" : action.tone === "primary" ? "default" : "outline"}
              onClick={() => sendInput(action)}
            >
              {action.label}
            </Button>
          ))}
        </div>
        <Terminal lines={status.logs} />
      </CardContent>
    </Card>
  )
}

function ProgressPanel({ status }: { status: WorkflowStatus }) {
  if (!status.progress.length && !status.status_line) return null
  return (
    <div className="grid gap-2 rounded-md border bg-muted/40 p-3">
      {status.progress.map((item) => (
        <div key={item.id} className="grid gap-1.5">
          <div className="flex items-center justify-between gap-3 text-xs">
            <span className="truncate font-medium">{item.label}</span>
            <span className="font-mono text-[10px] text-muted-foreground">
              {item.total == null ? number(item.current) : `${number(item.current)} / ${number(item.total)}`}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-border">
            <div
              className={cn("h-full bg-foreground transition-all", item.total == null && "w-1/3 animate-pulse")}
              style={item.total == null ? undefined : { width: `${Math.min(100, (item.current / item.total) * 100)}%` }}
            />
          </div>
          {(item.phase || item.detail) && <p className="truncate font-mono text-[10px] text-muted-foreground">{[item.phase, item.detail].filter(Boolean).join(" · ")}</p>}
        </div>
      ))}
      {status.status_line && <p className="truncate font-mono text-[10px] text-muted-foreground">{status.status_line.replace(/^\[RUN\]\s*/, "")}</p>}
    </div>
  )
}

function Terminal({ lines }: { lines: string[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const previous = useRef<string[]>([])
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const wasAtBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 48
    const appendOnly = lines.length >= previous.current.length && previous.current.every((line, index) => lines[index] === line)
    if (wasAtBottom || !appendOnly) node.scrollTop = node.scrollHeight
    previous.current = lines
  }, [lines])
  const visible = lines.length ? lines : ["Panel ready."]
  return (
    <div className="terminal min-h-64 flex-1 overflow-auto rounded-md border bg-[#0b0b0b] p-3 font-mono text-[11px] leading-5 text-[#ededed]" ref={ref} role="log">
      {visible.map((line, index) => <TerminalLine key={`${index}-${line}`} value={line} />)}
    </div>
  )
}

function TerminalLine({ value }: { value: string }) {
  const text = value.replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "")
  const match = text.match(/^(\s*)\[([A-Z]+)\](.*)$/)
  if (!match) return <div className="min-h-5 whitespace-pre-wrap break-words">{text}</div>
  return (
    <div className="min-h-5 whitespace-pre-wrap break-words">
      {match[1]}<span className="font-semibold text-white">[{match[2]}]</span>{match[3]}
    </div>
  )
}

function ConfigurationEditor({
  types,
  disabled,
  onCatalog,
  notify,
}: {
  types: ConfigurationType[]
  disabled: boolean
  onCatalog: (catalog: Catalog) => void
  notify: (message: string) => void
}) {
  const [kind, setKind] = useState(types[0]?.id ?? "")
  const definition = types.find((item) => item.id === kind) ?? types[0]
  const [source, setSource] = useState(definition?.templates[0]?.value ?? "")
  const [filename, setFilename] = useState("")
  const [content, setContent] = useState("")

  useEffect(() => setSource(definition?.templates[0]?.value ?? ""), [definition])

  const payload = () => ({ kind, filename, content })
  const load = async () => {
    try {
      const result = await post<{ content: string }>("/api/config/template", { kind, source })
      setContent(result.content)
      const sourceName = source.split("/").pop() || "new_config"
      const extension = definition?.extension || ""
      const stem = extension && sourceName.endsWith(extension) ? sourceName.slice(0, -extension.length) : sourceName
      setFilename(`${stem}_copy${extension}`)
      notify("Template loaded")
    } catch (error) {
      notify((error as Error).message)
    }
  }
  const validate = async () => {
    try {
      const result = await post<{ path: string }>("/api/config/validate", payload())
      notify(`Valid: ${result.path}`)
    } catch (error) {
      notify((error as Error).message)
    }
  }
  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (!window.confirm("Create this new validated repository configuration?")) return
    try {
      const result = await post<{ created: string; catalog: Catalog }>("/api/config/create", payload())
      onCatalog(result.catalog)
      setFilename("")
      setContent("")
      notify(`Created: ${result.created}`)
    } catch (error) {
      notify((error as Error).message)
    }
  }

  return (
    <Card className="min-h-[430px]">
      <CardHeader className="border-b p-5">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">CONFIGURATION</p>
        <CardTitle className="text-xl">Create from a validated template</CardTitle>
        <CardDescription>Atomic, create-only publication. Existing files are never overwritten.</CardDescription>
      </CardHeader>
      <CardContent className="p-5">
        <form className="grid gap-4" onSubmit={create}>
          <div className="grid gap-1.5">
            <Label>Configuration type</Label>
            <select value={kind} disabled={disabled} onChange={(event) => setKind(event.target.value)} className="h-9 rounded-md border bg-background px-3 text-sm">
              {types.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </div>
          <div className="grid gap-1.5">
            <Label>Template</Label>
            <select value={source} disabled={disabled} onChange={(event) => setSource(event.target.value)} className="h-9 rounded-md border bg-background px-3 text-sm">
              {definition?.templates.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </div>
          <div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={load}>Load template</Button><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={validate}>Validate</Button></div>
          <div className="grid gap-1.5"><Label>New filename</Label><Input value={filename} required disabled={disabled} placeholder={`my_new_config${definition?.extension || ""}`} onChange={(event) => setFilename(event.target.value)} /></div>
          <div className="grid gap-1.5"><Label>{definition?.language || "Configuration"}</Label><Textarea className="min-h-52 font-mono text-xs" value={content} required disabled={disabled} spellCheck={false} onChange={(event) => setContent(event.target.value)} /></div>
          <Button disabled={disabled}>Create configuration</Button>
        </form>
      </CardContent>
    </Card>
  )
}

function ConfigurationInventory({ groups }: { groups: Catalog["configuration_groups"] }) {
  return (
    <Card className="animate-reveal">
      <CardHeader className="border-b px-4 py-3">
        <CardTitle className="flex items-center gap-2 text-sm"><Database className="h-4 w-4" /> Tracked inventory</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-4">
        {groups.map((group) => (
          <div key={group.label} className="min-w-0">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">{group.label}</p>
            <div className="grid gap-1">
              {group.items.map((item) => <div key={item.value} className="truncate rounded border px-2 py-1.5 font-mono text-[10px]" title={item.value}>{item.label}</div>)}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function Toast({ message }: { message: string }) {
  return (
    <div className="fixed bottom-5 right-5 z-50 flex max-w-md items-center gap-2 rounded-md border border-white/20 bg-black px-4 py-3 text-sm text-white shadow-xl">
      <SquareTerminal className="h-4 w-4 shrink-0" /> {message}
    </div>
  )
}

function filteredOptions(field: Field, values: Json): Option[] {
  return (field.options ?? []).filter((option) => !field.depends_on || option.depends_value === values[field.depends_on])
}

function cameraUrl(camera: CameraDefinition): string {
  if (camera.url) return camera.url
  if (!Number.isInteger(camera.port) || !camera.path?.startsWith("/")) throw new Error(`Invalid camera endpoint: ${camera.id}`)
  return `${window.location.protocol}//${window.location.hostname}:${camera.port}${camera.path}`
}

function cameraState(health: CameraHealth | null, stream?: CameraStreamHealth): string {
  if (!health) return "Checking…"
  if (!health.available) return "Offline"
  if (!stream) return "Unavailable"
  if (stream.error) return "Stream error"
  if (!stream.ready) return "Waiting"
  if (!stream.fresh) return stream.age_s == null ? "Stale" : `Stale · ${age(stream.age_s)}`
  const fps = stream.preview_fps == null ? "Live" : `${stream.preview_fps.toFixed(1)} fps`
  return stream.age_s == null ? fps : `${fps} · ${age(stream.age_s)}`
}

function age(seconds: number): string {
  return seconds < 1 ? `${Math.round(seconds * 1000)} ms` : `${seconds.toFixed(1)} s`
}

function number(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function snakeCase(value: string): string {
  return value.normalize("NFKD").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "")
}
