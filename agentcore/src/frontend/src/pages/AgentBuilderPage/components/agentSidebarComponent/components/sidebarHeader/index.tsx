import { memo } from "react";

import { ForwardedIconComponent } from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import {
  Disclosure,
} from "@/components/ui/disclosure";
import { SidebarHeader, SidebarTrigger } from "@/components/ui/sidebar";
import type { SidebarHeaderComponentProps } from "../../types";
import { SearchInput } from "../searchInput";
import { SidebarFilterComponent } from "../sidebarFilterComponent";
import { useTranslation } from 'react-i18next';

export const SidebarHeaderComponent = memo(function SidebarHeaderComponent({
  showConfig,
  setShowConfig,
  showBeta,
  setShowBeta,
  showLegacy,
  setShowLegacy,
  searchInputRef,
  isInputFocused,
  search,
  handleInputFocus,
  handleInputBlur,
  handleInputChange,
  filterName,
  filterDescription,
  resetFilters,
  customComponent,
  addComponent,
  isLoading = false,
}: SidebarHeaderComponentProps) {
  const { t } = useTranslation();
  return (
    <SidebarHeader className="flex w-full flex-col gap-3 p-4 pb-2">
      <Disclosure open={showConfig} onOpenChange={setShowConfig}>
        <div className="flex w-full items-center gap-2">
          <SidebarTrigger className="text-muted-foreground">
            <ForwardedIconComponent name="PanelLeftClose" />
          </SidebarTrigger>
          <h3 className="flex-1 cursor-default text-sm font-semibold">
            {t("Components")}
          </h3>
        </div>
      </Disclosure>
      <SearchInput
        searchInputRef={searchInputRef}
        isInputFocused={isInputFocused}
        search={search}
        handleInputFocus={handleInputFocus}
        handleInputBlur={handleInputBlur}
        handleInputChange={handleInputChange}
      />
      <Button
        unstyled
        disabled={isLoading}
        onClick={() => {
          if (customComponent && addComponent) {
            addComponent(customComponent, "CustomComponent");
          }
        }}
        data-testid="sidebar-custom-component-button"
        className="flex h-9 w-full items-center justify-center gap-2 rounded-md border border-input bg-background hover:bg-muted"
      >
        <ForwardedIconComponent name="Plus" className="h-4 w-4 text-muted-foreground" />
        <span>{t("Create Custom")}</span>
      </Button>
      {filterName && filterDescription && (
        <SidebarFilterComponent
          name={filterName}
          description={filterDescription}
          resetFilters={resetFilters}
        />
      )}
    </SidebarHeader>
  );
});

SidebarHeaderComponent.displayName = "SidebarHeaderComponent";
