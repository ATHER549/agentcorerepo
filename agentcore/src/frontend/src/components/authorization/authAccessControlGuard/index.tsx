import useAuthStore from "@/stores/authStore";
import { LoadingPage } from "@/pages/LoadingPage";
import AccessDeniedPage from "@/pages/AccessDeniedPage";

export const ProtectedAccessControlRoute = ({
  children,
}: {
  children: JSX.Element;
}) => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const role = useAuthStore((state) => state.role);

  if (!isAuthenticated) {
    return <LoadingPage />;
  }

  const canAccess = role === "root";

  if (!canAccess) {
    return (
      <AccessDeniedPage message="You do not have access to manage roles and permissions." />
    );
  }

  return children;
};
