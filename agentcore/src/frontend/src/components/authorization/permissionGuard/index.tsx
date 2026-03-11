import useAuthStore from "@/stores/authStore";
import { LoadingPage } from "@/pages/LoadingPage";
import AccessDeniedPage from "@/pages/AccessDeniedPage";

export const ProtectedPermissionRoute = ({
  children,
  permission,
}: {
  children: JSX.Element;
  permission: string;
}) => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const permissions = useAuthStore((state) => state.permissions);

  if (!isAuthenticated) {
    return <LoadingPage />;
  }

  if (!permissions.includes(permission)) {
    return (
      <AccessDeniedPage message={`Missing permission: ${permission}`} />
    );
  }

  return children;
};
