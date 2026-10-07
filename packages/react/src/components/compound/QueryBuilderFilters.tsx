import React from "react";
import type { QueryBuilderClassNames } from "../../types";
import { useCompoundQueryBuilder } from "./QueryBuilderContext";
import { TableFiltersEditor } from "../TableFiltersEditor";

export interface QueryBuilderFiltersProps {
  /** Optional container class name */
  className?: string;
  /** Granular slot class names mapping */
  classNames?: QueryBuilderClassNames;
  /** Unstyled mode flag */
  unstyled?: boolean;
}

export const QueryBuilderFilters: React.FC<QueryBuilderFiltersProps> = ({
  className,
  classNames: propClassNames,
  unstyled: propUnstyled,
}) => {
  const {
    filters,
    activeTables,
    actions,
    unstyled: rootUnstyled,
    classNames: rootClassNames,
    customOperators,
  } = useCompoundQueryBuilder();

  const unstyled = propUnstyled ?? rootUnstyled;
  const classNames = propClassNames || rootClassNames;

  return (
    <TableFiltersEditor
      filters={filters}
      activeTables={activeTables}
      onChange={actions.setFilters}
      unstyled={unstyled}
      customOperators={customOperators}
      className={className}
      classNames={classNames}
    />
  );
};
