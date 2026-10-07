import React from "react";
import type { QueryBuilderClassNames } from "../../types";
import { useCompoundQueryBuilder } from "./QueryBuilderContext";
import { TableSortsEditor } from "../TableSortsEditor";

export interface QueryBuilderSortsProps {
  /** Optional container class name */
  className?: string;
  /** Granular slot class names mapping */
  classNames?: QueryBuilderClassNames;
  /** Unstyled mode flag */
  unstyled?: boolean;
}

export const QueryBuilderSorts: React.FC<QueryBuilderSortsProps> = ({
  className,
  classNames: propClassNames,
  unstyled: propUnstyled,
}) => {
  const {
    sorts,
    activeTables,
    actions,
    unstyled: rootUnstyled,
    classNames: rootClassNames,
  } = useCompoundQueryBuilder();

  const unstyled = propUnstyled ?? rootUnstyled;
  const classNames = propClassNames || rootClassNames;

  return (
    <TableSortsEditor
      sorts={sorts}
      activeTables={activeTables}
      onChange={actions.setSorts}
      unstyled={unstyled}
      className={className}
      classNames={classNames}
    />
  );
};
