import { FaDiscord, FaGithub } from "react-icons/fa";
import { ForwardedIconComponent } from "@/components/common/genericIconComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { useLogout } from "@/controllers/API/queries/auth";
import { CustomProfileIcon } from "@/customization/components/custom-profile-icon";
import { ENABLE_AGENTCORE } from "@/customization/feature-flags";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { useDarkStore } from "@/stores/darkStore";
import { stripReleaseStageFromVersion } from "@/utils/utils";
import {
  HeaderMenu,
  HeaderMenuItemButton,
  HeaderMenuItemLink,
  HeaderMenuItems,
  HeaderMenuToggle,
} from "../HeaderMenu";
import ThemeButtons from "../ThemeButtons";
import useAuthStore from "@/stores/authStore";
import { useContext } from "react";
import { AuthContext } from "@/contexts/authContext";
import { useTranslation } from "react-i18next";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { resolvePreferredLocale, SUPPORTED_LOCALES } from "@/i18n";

export const AccountMenu = () => {
  const { t, i18n } = useTranslation();
  const version = useDarkStore((state) => state.version);
  const latestVersion = useDarkStore((state) => state.latestVersion);
  const currentReleaseVersion = useDarkStore((state) => state.currentReleaseVersion);
  const navigate = useCustomNavigate();
  const { mutate: mutationLogout } = useLogout();
  const { permissions, role, userData } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const username = (userData?.username || t("User")).trim();
  const fallbackName = username.includes("@") ? username.split("@")[0] : username;
  const displayName = (fallbackName || t("User")).trim();
  const email = (userData?.email || (username.includes("@") ? username : "")).trim();
  const organizationName = userData?.organization_name || userData?.department_name || t("N/A");
  const displayRole = role ? role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : t("N/A");
  const showOrganization = role !== "root";
  const initialsSource = displayName.replace(/\s+/g, "");
  const initials = (initialsSource.slice(0, 2) || t("US")).toUpperCase();

  const selectedLanguage = resolvePreferredLocale(i18n.resolvedLanguage);
  const languageOptions = SUPPORTED_LOCALES.map((locale) => {
    const languageCode = locale.split("-")[0];
    const languageName = new Intl.DisplayNames([locale], {
      type: "language",
    }).of(languageCode);
    return {
      value: locale,
      label: languageName ? `${languageName} (${locale})` : locale,
    };
  });

  const handleLogout = () => {
    mutationLogout();
  };

  const handleLanguageChange = (language: string) => {
    void i18n.changeLanguage(language);
    localStorage.setItem("locale", language);
  };

  const isLatestVersion = (() => {
    if (!version || !latestVersion) return false;

    const currentBaseVersion = stripReleaseStageFromVersion(version);
    const latestBaseVersion = stripReleaseStageFromVersion(latestVersion);

    return currentBaseVersion === latestBaseVersion;
  })();
  const visibleVersion = currentReleaseVersion || version || "-";

  return (
    <HeaderMenu>
      <HeaderMenuToggle>
        <div
          className="h-6 w-6 rounded-lg focus-visible:outline-0"
          data-testid="user-profile-settings"
        >
          <CustomProfileIcon />
        </div>
      </HeaderMenuToggle>
      <HeaderMenuItems position="right" classNameSize="w-[300px]">
        <div className="divide-y divide-foreground/10">
          <div className="px-4 py-3">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground">
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold leading-4 text-foreground">
                  {displayName}
                </div>
                {email ? (
                  <ShadTooltip
                    content={email}
                    side="bottom"
                    align="start"
                    styleClasses="max-w-none whitespace-normal break-all bg-popover text-popover-foreground border border-border shadow-md"
                  >
                    <div
                      className="truncate pt-0.5 text-[11px] text-muted-foreground"
                      title={email}
                    >
                      {email}
                    </div>
                  </ShadTooltip>
                ) : null}
              </div>
            </div>
            <div className="mt-2 grid grid-cols-[84px_1fr] items-center gap-x-2 gap-y-0.5 pl-11 text-[11px]">
              {showOrganization ? (
                <>
                  <span className="text-muted-foreground">{t("Organization")}</span>
                  <span className="truncate text-foreground">{organizationName}</span>
                </>
              ) : null}
              <span className="text-muted-foreground">{t("Role")}</span>
              <span className="truncate text-foreground">{displayRole}</span>
              <span className="text-muted-foreground">{t("Release")}</span>
              <span className="truncate text-foreground">{visibleVersion}</span>
            </div>
          </div>
          <div>
            <HeaderMenuItemButton
              onClick={() => {
                navigate("/settings");
              }}
            >
              <span
                data-testid="menu_settings_button"
                id="menu_settings_button"
              >
                {t("Settings")}
              </span>
            </HeaderMenuItemButton>

            {can("view_admin_page") && (
              <div>
                <HeaderMenuItemButton
                  onClick={() => {
                    navigate("/admin");
                  }}
                >
                  <span
                    data-testid="menu_admin_page_button"
                    id="menu_admin_page_button"
                  >
                    {t("Admin Page")}
                  </span>
                </HeaderMenuItemButton>
              </div>
            )}
            {role === "root" && (
              <div>
                <HeaderMenuItemButton
                  onClick={() => {
                    navigate("/access-control");
                  }}
                >
                  <span
                    data-testid="menu_access_control_button"
                    id="menu_access_control_button"
                  >
                    {t("Access Control")}
                  </span>
                </HeaderMenuItemButton>
              </div>
            )}
            
          </div>

          

          <div className="flex items-center justify-between px-4 py-[6.5px] text-sm">
            <span className="">{t("Theme")}</span>
            <div className="relative top-[1px] float-right">
              <ThemeButtons />
            </div>
          </div>
          <div className="flex items-center justify-between px-4 py-[6.5px] text-sm">
            <span>{t("Preferred Language")}</span>
            <Select value={selectedLanguage} onValueChange={handleLanguageChange}>
              <SelectTrigger className="h-8 w-[180px] px-2 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-h-56 overflow-y-auto">
                {languageOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          
            <div>
              <HeaderMenuItemButton onClick={handleLogout} icon="log-out">
                {t("Logout")}
              </HeaderMenuItemButton>
            </div>
        
        </div>
      </HeaderMenuItems>
    </HeaderMenu>
  );
};
