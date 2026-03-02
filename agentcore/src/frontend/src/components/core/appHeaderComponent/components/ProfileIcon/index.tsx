import { useContext } from "react";
import { AuthContext } from "@/contexts/authContext";

export function ProfileIcon() {
  const { userData } = useContext(AuthContext);

  const username = (userData?.username ?? "").trim();
  const initials = (username.slice(0, 2) || "US").toUpperCase();

  return (
    <div
      className="h-6 w-6 shrink-0 rounded-full bg-primary text-primary-foreground text-[10px] font-semibold flex items-center justify-center select-none focus-visible:outline-0"
      aria-label={username ? `${username} profile` : "User profile"}
      title={username || "User"}
    >
      {initials}
    </div>
  );
}
