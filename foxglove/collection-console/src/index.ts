import { ExtensionContext } from "@foxglove/extension";

import { initCollectionConsole } from "./CollectionConsole";

export function activate(extensionContext: ExtensionContext): void {
  extensionContext.registerPanel({
    name: "Collection Console",
    initPanel: initCollectionConsole,
  });
}
