import { Outlet, type To } from "react-router-dom";
import { useTranslation } from "react-i18next";
import SideBarButtonsComponent from "@/components/core/sidebarComponent";
import { SidebarProvider } from "@/components/ui/sidebar";
import { useStoreStore } from "@/stores/storeStore";
import ForwardedIconComponent from "../../components/common/genericIconComponent";
import PageLayout from "../../components/common/pageLayout";
export default function SettingsPage(): JSX.Element {
  const { t } = useTranslation();
  const hasStore = useStoreStore((state) => state.hasStore);



  const sidebarNavItems: {
    href?: string;
    title: string;
    icon: React.ReactNode;
    permissionKey?: string;
  }[] = [];

 

  sidebarNavItems.push(
    {
      title: t("Global Variables"),
      href: "/settings/global-variables",
      icon: (
        <ForwardedIconComponent
          name="Globe"
          className="w-4 flex-shrink-0 justify-start stroke-[1.5]"
        />
      ),
      permissionKey: "view_settings_global_variables_tab",
    },

    {
      title: t("Shortcuts"),
      href: "/settings/shortcuts",
      icon: (
        <ForwardedIconComponent
          name="Keyboard"
          className="w-4 flex-shrink-0 justify-start stroke-[1.5]"
        />
      ),
      permissionKey: "view_settings_shortcuts_tab",
    },
    {
      title: t("Messages"),
      href: "/settings/messages",
      icon: (
        <ForwardedIconComponent
          name="MessagesSquare"
          className="w-4 flex-shrink-0 justify-start stroke-[1.5]"
        />
      ),
      permissionKey: "view_settings_messages_tab",
    },
  );



  return (
    <PageLayout
      backTo={-1 as To}
      title={t("Settings")}
      description={t("Manage the general settings for AgentCore.")}
    >
      <SidebarProvider width="15rem" defaultOpen={false}>
        <SideBarButtonsComponent items={sidebarNavItems} />
        <main className="flex flex-1 overflow-hidden">
          <div className="flex flex-1 flex-col overflow-x-hidden pt-1">
            <Outlet />
          </div>
        </main>
      </SidebarProvider>
    </PageLayout>
  );
}
