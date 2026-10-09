import { useEffect, useState } from "react";
import type { SchemaSnapshot, DatabaseSchemaDefinition, TableSchema } from "../../types";
import type { QueryBuilderClient } from "../../client";

/**
 * Auto-wires a schema snapshot (when no `schema` prop is given) and engine capabilities
 * from a `QueryBuilderClient`. Failures are logged and non-fatal.
 */
export function useClientBootstrap(
  client: QueryBuilderClient | undefined,
  propSchema: DatabaseSchemaDefinition | SchemaSnapshot | TableSchema[] | null | undefined,
) {
  const [clientSchema, setClientSchema] = useState<SchemaSnapshot | null>(null);

  useEffect(() => {
    if (!propSchema && client && !clientSchema) {
      client
        .getSchema()
        .then((s) => {
          if (s) setClientSchema(s);
        })
        .catch((err) => {
          console.warn("[Query-Builder] Failed to auto-fetch schema from client:", err);
        });
    }
  }, [propSchema, client, clientSchema]);

  const [serverCapabilities, setServerCapabilities] = useState<Record<string, string> | null>(null);

  useEffect(() => {
    if (client && !serverCapabilities && typeof client.getCapabilities === "function") {
      client
        .getCapabilities()
        .then((caps) => {
          if (caps && Object.keys(caps).length > 0) {
            setServerCapabilities(caps);
          }
        })
        .catch((err) => {
          console.warn("[Query-Builder] Failed to auto-fetch capabilities from client:", err);
        });
    }
  }, [client, serverCapabilities]);

  return { clientSchema, serverCapabilities };
}
