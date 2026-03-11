import useAuthStore from "@/stores/authStore";
import { CustomNavigate } from "@/customization/components/custom-navigate";
import { LoadingPage } from "@/pages/LoadingPage";

export const ProtectedAdminRoute = ({
  children,
}: {
  children: JSX.Element;
}) => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const permissions = useAuthStore((state) => state.permissions);

  // 1️⃣ Wait until auth is resolved
  if (!isAuthenticated) {
    return <LoadingPage />;
  }

  // 2️⃣ Centralized admin permission rule
  const canAccessAdmin = permissions.includes("view_admin_page");

  // 3️⃣ Block if permission missing
  if (!canAccessAdmin) {
    return <CustomNavigate to="/" replace />;
  }

  // 4️⃣ Allowed
  return children;
};

