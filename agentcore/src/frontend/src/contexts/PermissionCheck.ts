import useAuthStore from "@/stores/authStore";

export const usePermissionAny = (required: string[]): boolean => {
  const permissions = useAuthStore((s) => s.permissions);
  return required.some((p) => permissions.includes(p));
};

export const usePermissionAll = (required: string[]): boolean => {
  const permissions = useAuthStore((s) => s.permissions);
  return required.every((p) => permissions.includes(p));
};
