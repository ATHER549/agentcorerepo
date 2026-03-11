export const sortAgents = (agents, type) => {
  const isComponent = type === "component";

  const sortByDateFn = (a, b) => {
    const dateA = a?.updated_at || a?.date_created;
    const dateB = b?.updated_at || b?.date_created;

    return sortByDate(dateA, dateB);
  };

  const filteredAgents =
    type === "all"
      ? agents
      : agents?.filter((f) => (f?.is_component ?? false) === isComponent);

  return filteredAgents?.sort(sortByDateFn) ?? [];
};

export const sortByDate = (dateA: string, dateB: string) => {
  if (dateA && dateB) {
    return new Date(dateB).getTime() - new Date(dateA).getTime();
  } else if (dateA) {
    return 1;
  } else if (dateB) {
    return -1;
  } else {
    return 0;
  }
};

export const sortByBoolean = (a: boolean, b: boolean) => {
  if (a && b) {
    return 0;
  } else if (a && !b) {
    return -1;
  } else if (!a && b) {
    return 1;
  } else {
    return 0;
  }
};
