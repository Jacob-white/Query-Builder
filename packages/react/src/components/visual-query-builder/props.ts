import type {
  VisualQueryBuilderProps,
  DatabaseSchemaDefinition,
  QueryPlanNode,
  CteSpec,
  WindowFunctionSpec,
  SemanticModel,
  SchemaSnapshot,
} from "../../types";
import type { QueryBuilderTheme } from "../../theme/tokens";
import type { NlqProviderName } from "../../hooks/useNlqQuery";
import type { LiveExecutionResult } from "../../hooks/useLiveExecution";
import type {
  DatabaseConnectionInfo,
  DatabaseConnectionConfig,
  DatabaseTestResult,
} from "../DatabaseConnectionModal";

export type ExtendedVisualQueryBuilderProps<Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition> = Omit<
  VisualQueryBuilderProps<Schema>,
  "theme"
> & {
  theme?: "dark" | "light" | "auto" | QueryBuilderTheme;
  unstyled?: boolean;
  queryPlan?: QueryPlanNode;
  showPlanTab?: boolean;
  showNlqBar?: boolean;
  hideNlqBar?: boolean;
  compactHeader?: boolean;
  nlqApiUrl?: string;
  nlqDefaultProvider?: NlqProviderName;
  showLiveExecutionBar?: boolean;
  liveExecutionApiUrl?: string;
  liveExecutionConnectionId?: string;
  onLiveExecutionSuccess?: (results: LiveExecutionResult) => void;
  onLiveExecutionError?: (error: Error) => void;
  initialCtes?: CteSpec[];
  initialWindowFunctions?: WindowFunctionSpec[];
  showPipelineTab?: boolean;
  semanticModels?: SemanticModel[];
  hideInnerToolbar?: boolean;
  hideSummaryBar?: boolean;
  studioMode?: boolean;
  showConnectDatabaseButton?: boolean;
  databaseApiUrl?: string;
  databases?: DatabaseConnectionInfo[];
  activeDatabaseId?: string;
  onSelectDatabase?: (dbId: string) => void;
  onDatabaseConnected?: (db: DatabaseConnectionInfo, schema?: SchemaSnapshot) => void;
  onDatabaseDisconnected?: (dbId: string) => void;
  onTestDatabaseConnection?: (config: DatabaseConnectionConfig) => Promise<DatabaseTestResult>;
  onConnectDatabase?: (
    config: DatabaseConnectionConfig,
  ) => Promise<{ database: DatabaseConnectionInfo; schema?: SchemaSnapshot }>;
  onDisconnectDatabase?: (dbId: string) => Promise<void>;
};
