import type { QueryBuilderTheme } from "../../theme/tokens";
import type { QueryBuilderClassNames } from "../../types";

export type ActiveTab = "visual" | "sql" | "results" | "chart" | "plan" | "pipeline";

/** Props shared by the presentational units of the builder. */
export interface ThemedProps {
  unstyled: boolean;
  theme: QueryBuilderTheme;
  classNames?: QueryBuilderClassNames;
}
