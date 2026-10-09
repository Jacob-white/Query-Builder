import type {
  VisualQueryBuilderProps,
  DatabaseSchemaDefinition,
  QueryPlanNode,
  CteSpec,
  WindowFunctionSpec,
  SemanticModel,
} from "../../types";
import type { QueryBuilderTheme } from "../../theme/tokens";
import type { NlqProviderName } from "../../hooks/useNlqQuery";
import type { LiveExecutionResult } from "../../hooks/useLiveExecution";

export type ExtendedVisualQueryBuilderProps<Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition> = Omit<
  VisualQueryBuilderProps<Schema>,
  "theme"
> & {
  theme?: "dark" | "light" | "auto" | QueryBuilderTheme;
  unstyled?: boolean;
  queryPlan?: QueryPlanNode;
  showPlanTab?: boolean;
  showNlqBar?: boolean;
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
};
