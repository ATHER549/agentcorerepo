import useAuthStore from "@/stores/authStore";

export const hasPermission = (permission: string): boolean => {
  const permissions = useAuthStore.getState().permissions ?? [];
  return Array.isArray(permissions) && permissions.includes(permission);
};
