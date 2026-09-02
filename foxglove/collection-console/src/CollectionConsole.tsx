import { MessageEvent, PanelExtensionContext } from "@foxglove/extension";
import {
  CSSProperties,
  ReactElement,
  useCallback,
  useEffect,
  useLayoutEffect,
  useState,
} from "react";
import { createRoot } from "react-dom/client";

type Progress = {
  id: string;
  label: string;
  current: number;
  total: number | null;
  phase: string;
  detail: string;
};

type WorkflowStatus = {
  available: boolean;
  error: string;
  active: boolean;
  runId: string;
  state: string;
  workflow: string;
  name: string;
  inputPhase: string;
  inputDetail: string;
  inputActions: string[];
  progress: Progress[];
};

type ServiceName = "start" | "save" | "discard" | "reset" | "stop";

type CollectionConsoleConfig = {
  schemaVersion: 1;
  statusTopic: string;
  services: Record<ServiceName, string>;
  staleAfterMs: number;
};

type Control = {
  service: ServiceName;
  label: string;
  phase?: "ready" | "recording";
  confirm?: string;
};

const SERVICE_NAMES: ServiceName[] = ["start", "save", "discard", "reset", "stop"];

const CONTROLS: Control[] = [
  {
    service: "start",
    label: "Start recording",
    phase: "ready",
  },
  {
    service: "save",
    label: "Stop and save",
    phase: "recording",
  },
  {
    service: "reset",
    label: "Reset position",
    phase: "ready",
    confirm: "Reset the powered robot to the tracked collection start pose?",
  },
  {
    service: "discard",
    label: "Discard episode",
    phase: "recording",
    confirm: "Discard the current episode without saving it?",
  },
  {
    service: "stop",
    label: "End session",
    confirm: "Stop the active collection session?",
  },
];

const EMPTY_STATUS: WorkflowStatus = {
  available: false,
  error: "Waiting for workflow telemetry",
  active: false,
  runId: "",
  state: "idle",
  workflow: "",
  name: "",
  inputPhase: "",
  inputDetail: "",
  inputActions: [],
  progress: [],
};

type ConfigurationResult =
  | { config: CollectionConsoleConfig; error?: never }
  | { config?: never; error: string };

function CollectionConsole({ context }: { context: PanelExtensionContext }): ReactElement {
  const [configuration] = useState<ConfigurationResult>(() => readConfiguration(context.initialState));
  const [status, setStatus] = useState<WorkflowStatus>(EMPTY_STATUS);
  const [receivedAt, setReceivedAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [busy, setBusy] = useState<ServiceName>();
  const [controlError, setControlError] = useState("");
  const [colorScheme, setColorScheme] = useState<"dark" | "light">("dark");
  const [renderDone, setRenderDone] = useState<(() => void) | undefined>();

  useLayoutEffect(() => {
    context.onRender = (renderState, done) => {
      if (renderState.colorScheme != undefined) {
        setColorScheme(renderState.colorScheme);
      }
      if (configuration.config != undefined) {
        const event = latestStatusEvent(
          renderState.currentFrame,
          configuration.config.statusTopic,
        );
        if (event != undefined) {
          try {
            setStatus(parseStatusMessage(event.message));
            setReceivedAt(Date.now());
          } catch (error) {
            setStatus({
              ...EMPTY_STATUS,
              error: error instanceof Error ? error.message : "Invalid workflow telemetry",
            });
            setReceivedAt(Date.now());
          }
        }
      }
      setRenderDone(() => done);
    };
    context.watch("currentFrame");
    context.watch("colorScheme");
    if (configuration.config != undefined) {
      context.subscribe([{ topic: configuration.config.statusTopic }]);
    }
    return () => {
      context.unsubscribeAll();
      context.onRender = undefined;
    };
  }, [configuration, context]);

  useEffect(() => {
    renderDone?.();
  }, [renderDone, status, colorScheme]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 500);
    return () => {
      window.clearInterval(timer);
    };
  }, []);

  const stale =
    configuration.config == undefined ||
    receivedAt === 0 ||
    now - receivedAt > configuration.config.staleAfterMs;
  const controlsAvailable = context.callService != undefined;

  const invoke = useCallback(
    async (control: Control) => {
      if (control.confirm != undefined && !window.confirm(control.confirm)) {
        return;
      }
      if (context.callService == undefined || configuration.config == undefined) {
        setControlError("Service calls unavailable");
        return;
      }
      setBusy(control.service);
      setControlError("");
      try {
        const response = await context.callService(
          configuration.config.services[control.service],
          {},
        );
        const result = serviceResponse(response);
        if (!result.success) {
          throw new Error(result.message || `${control.label} rejected`);
        }
      } catch (error) {
        setControlError(error instanceof Error ? error.message : `${control.label} failed`);
      } finally {
        setBusy(undefined);
      }
    },
    [configuration, context],
  );

  const palette = colorScheme === "dark" ? DARK_PALETTE : LIGHT_PALETTE;
  const rootStyle: CSSProperties = {
    minHeight: "100%",
    boxSizing: "border-box",
    padding: 12,
    color: palette.text,
    background: "transparent",
    fontFamily: "Inter, system-ui, sans-serif",
  };

  return (
    <main style={rootStyle}>
      <div
        role="status"
        style={{
          padding: "10px 12px",
          border: `1px solid ${palette.border}`,
          borderRadius: 4,
          fontSize: 16,
          fontWeight: 600,
        }}
      >
        {configuration.error ?? statusLabel(status, { stale })}
      </div>

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          gap: 8,
          marginTop: 10,
        }}
      >
        {CONTROLS.map((control) => {
          const enabled = controlEnabled(control, status, {
            stale,
            busy,
            servicesAvailable: controlsAvailable,
          });
          return (
            <button
              key={control.service}
              type="button"
              disabled={!enabled}
              onClick={() => void invoke(control)}
              style={buttonStyle({ enabled, palette })}
            >
              {busy === control.service ? "Working…" : control.label}
            </button>
          );
        })}
      </section>

      {controlError ? (
        <div style={{ marginTop: 8, fontSize: 11, color: palette.muted }}>{controlError}</div>
      ) : undefined}
    </main>
  );
}

function readConfiguration(value: unknown): ConfigurationResult {
  try {
    return { config: parseConfiguration(value) };
  } catch (error) {
    return {
      error: error instanceof Error ? error.message : "Invalid panel configuration",
    };
  }
}

function parseConfiguration(value: unknown): CollectionConsoleConfig {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["schemaVersion", "services", "staleAfterMs", "statusTopic"]) ||
    value.schemaVersion !== 1 ||
    typeof value.statusTopic !== "string" ||
    value.statusTopic.length === 0 ||
    typeof value.staleAfterMs !== "number" ||
    !Number.isInteger(value.staleAfterMs) ||
    value.staleAfterMs < 500
  ) {
    throw new Error("Invalid collection console configuration");
  }
  const serviceValues = value.services;
  if (
    !isRecord(serviceValues) ||
    !hasExactKeys(serviceValues, SERVICE_NAMES) ||
    SERVICE_NAMES.some(
      (name) =>
        typeof serviceValues[name] !== "string" || serviceValues[name].length === 0,
    )
  ) {
    throw new Error("Invalid collection console configuration");
  }
  const services = Object.fromEntries(
    SERVICE_NAMES.map((name) => [name, serviceValues[name] as string]),
  ) as Record<ServiceName, string>;
  if (new Set(Object.values(services)).size !== SERVICE_NAMES.length) {
    throw new Error("Collection service names must be unique");
  }
  return {
    schemaVersion: 1,
    statusTopic: value.statusTopic,
    services,
    staleAfterMs: value.staleAfterMs,
  };
}

function latestStatusEvent(
  frame: readonly MessageEvent[] | undefined,
  topic: string,
): MessageEvent | undefined {
  const matches = frame?.filter((event) => event.topic === topic);
  return matches?.[matches.length - 1];
}

function parseStatusMessage(message: unknown): WorkflowStatus {
  if (!isRecord(message) || typeof message.data !== "string") {
    throw new Error("Workflow status is not std_msgs/String");
  }
  const value: unknown = JSON.parse(message.data);
  if (!isRecord(value) || value.schema_version !== 2 || typeof value.available !== "boolean") {
    throw new Error("Workflow status schema mismatch");
  }
  if (!value.available) {
    return {
      ...EMPTY_STATUS,
      error: typeof value.error === "string" ? value.error : "Operator Session unavailable",
    };
  }
  const requiredStrings = [
    "run_id",
    "state",
    "workflow",
    "name",
    "input_phase",
    "input_detail",
  ] as const;
  if (
    typeof value.active !== "boolean" ||
    requiredStrings.some((key) => typeof value[key] !== "string") ||
    !Array.isArray(value.input_actions) ||
    !Array.isArray(value.progress)
  ) {
    throw new Error("Workflow status fields are invalid");
  }
  const inputActions = value.input_actions.map((item) => {
    if (!isRecord(item) || typeof item.id !== "string") {
      throw new Error("Workflow input action is invalid");
    }
    return item.id;
  });
  return {
    available: true,
    error: "",
    active: value.active,
    runId: value.run_id as string,
    state: value.state as string,
    workflow: value.workflow as string,
    name: value.name as string,
    inputPhase: value.input_phase as string,
    inputDetail: value.input_detail as string,
    inputActions,
    progress: value.progress.map(parseProgress),
  };
}

function parseProgress(value: unknown): Progress {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.label !== "string" ||
    typeof value.current !== "number" ||
    !("total" in value) ||
    (value.total != null && typeof value.total !== "number") ||
    typeof value.phase !== "string" ||
    typeof value.detail !== "string"
  ) {
    throw new Error("Workflow progress is invalid");
  }
  return {
    id: value.id,
    label: value.label,
    current: value.current,
    total: typeof value.total === "number" ? value.total : null,
    phase: value.phase,
    detail: value.detail,
  };
}

function serviceResponse(value: unknown): { success: boolean; message: string } {
  if (!isRecord(value) || typeof value.success !== "boolean") {
    throw new Error("ROS Trigger returned an invalid response");
  }
  return {
    success: value.success,
    message: typeof value.message === "string" ? value.message : "",
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value != null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const normalizedExpected = [...expected].sort();
  return (
    actual.length === normalizedExpected.length &&
    actual.every((key, index) => key === normalizedExpected[index])
  );
}

function statusLabel(status: WorkflowStatus, { stale }: { stale: boolean }): string {
  if (stale) {
    return "Offline";
  }
  if (!status.available) {
    return "No session";
  }
  if (!status.active) {
    if (status.state === "succeeded") {
      return "Completed";
    }
    if (status.state === "failed") {
      return "Failed";
    }
    if (status.state === "stopped") {
      return "Stopped";
    }
    return "Idle";
  }
  if (status.inputPhase === "ready") {
    return "Ready";
  }
  if (status.inputPhase === "recording") {
    return "Recording";
  }
  const progressPhase =
    status.progress.find((item) => item.id === "collection")?.phase ??
    status.progress[status.progress.length - 1]?.phase;
  const labels: Record<string, string> = {
    saving: "Saving",
    discarding: "Discarding",
    resetting: "Resetting",
    stopping: "Stopping",
    completed: "Completed",
  };
  return labels[progressPhase ?? ""] ?? "Running";
}

function controlEnabled(
  control: Control,
  status: WorkflowStatus,
  {
    stale,
    busy,
    servicesAvailable,
  }: {
    stale: boolean;
    busy: ServiceName | undefined;
    servicesAvailable: boolean;
  },
): boolean {
  if (stale || busy != undefined || !servicesAvailable || !status.available || !status.active) {
    return false;
  }
  if (control.service === "stop") {
    return status.workflow === "collect" && status.state !== "stopping";
  }
  return (
    status.workflow === "collect" &&
    status.state === "waiting_for_input" &&
    status.inputPhase === control.phase &&
    status.inputActions.includes(control.service)
  );
}

type Palette = typeof DARK_PALETTE;

const DARK_PALETTE = {
  surface: "#202124",
  border: "#4b4d52",
  text: "#f1f1f1",
  muted: "#a5a7ac",
};

const LIGHT_PALETTE: Palette = {
  surface: "#ffffff",
  border: "#c7c9cc",
  text: "#202124",
  muted: "#666a70",
};

function buttonStyle({ enabled, palette }: { enabled: boolean; palette: Palette }): CSSProperties {
  return {
    minHeight: 44,
    padding: "8px 10px",
    borderRadius: 4,
    border: `1px solid ${palette.border}`,
    background: palette.surface,
    color: palette.text,
    cursor: enabled ? "pointer" : "not-allowed",
    opacity: enabled ? 1 : 0.4,
    textAlign: "center",
    fontSize: 12,
    fontWeight: 600,
  };
}

export function initCollectionConsole(context: PanelExtensionContext): () => void {
  const root = createRoot(context.panelElement);
  root.render(<CollectionConsole context={context} />);
  return () => {
    root.unmount();
  };
}
