import { ExtensionContext } from "@foxglove/extension";

import { initTeleopControls } from "./TeleopControls";

export function activate(extensionContext: ExtensionContext): void {
  extensionContext.registerPanel({ name: "controls", initPanel: initTeleopControls });
}
