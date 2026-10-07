import React from "react";
import type { QueryBuilderClassNames } from "../../types";
import { useCompoundQueryBuilder } from "./QueryBuilderContext";
import { TableJoinEditor } from "../TableJoinEditor";

export interface QueryBuilderJoinsProps {
  /** Optional container class name */
  className?: string;
  /** Granular slot class names mapping */
  classNames?: QueryBuilderClassNames;
  /** Unstyled mode flag */
  unstyled?: boolean;
}

export const QueryBuilderJoins: React.FC<QueryBuilderJoinsProps> = ({
  className,
  classNames: propClassNames,
  unstyled: propUnstyled,
}) => {
  const {
    joins,
    activeTables,
    normalizedSchema,
    actions,
    unstyled: rootUnstyled,
    classNames: rootClassNames,
  } = useCompoundQueryBuilder();

  const unstyled = propUnstyled ?? rootUnstyled;
  const classNames = propClassNames || rootClassNames;

  const allTables = Object.values(normalizedSchema?.tables || {});

  return (
    <TableJoinEditor
      joins={joins}
      activeTables={activeTables}
      allTables={allTables}
      schema={normalizedSchema}
      onChange={actions.setJoins}
      unstyled={unstyled}
      className={className}
      classNames={classNames}
    />
  );
};
