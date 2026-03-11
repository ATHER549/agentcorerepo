import { memo } from "react";

import { ForwardedIconComponent } from "@/components/common/genericIconComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { Button } from "@/components/ui/button";
import {
  Disclosure,
  DisclosureContent,
  DisclosureTrigger,
} from "@/components/ui/disclosure";
import { SidebarHeader, SidebarTrigger } from "@/components/ui/sidebar";
import type { SidebarHeaderComponentProps } from "../../types";
import FeatureToggles from "../featureTogglesComponent";
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
  filterType,
  setFilterEdge,
  setFilterData,
  data,
}: SidebarHeaderComponentProps) {
  const { t } = useTranslation();
  return (
    <SidebarHeader className="flex w-full flex-col gap-4 p-4 pb-1">
      <Disclosure open={showConfig} onOpenChange={setShowConfig}>
        <div className="flex w-full items-center gap-2">
          <SidebarTrigger className="text-muted-foreground">
            <ForwardedIconComponent name="PanelLeftClose" />
          </SidebarTrigger>
          <h3 className="flex-1 cursor-default text-sm font-semibold">
            {t("Components")}
          </h3>
          <DisclosureTrigger>
            <div>
             
            </div>
          </DisclosureTrigger>
        </div>
        <DisclosureContent>
          <FeatureToggles
            showBeta={showBeta}
            setShowBeta={setShowBeta}
            showLegacy={showLegacy}
            setShowLegacy={setShowLegacy}
          />
        </DisclosureContent>
      </Disclosure>
      <SearchInput
        searchInputRef={searchInputRef}
        isInputFocused={isInputFocused}
        search={search}
        handleInputFocus={handleInputFocus}
        handleInputBlur={handleInputBlur}
        handleInputChange={handleInputChange}
      />
      {filterType && (
        <SidebarFilterComponent
          isInput={!!filterType.source}
          type={filterType.type}
          color={filterType.color}
          resetFilters={() => {
            setFilterEdge([]);
            setFilterData(data);
          }}
        />
      )}
    </SidebarHeader>
  );
});

SidebarHeaderComponent.displayName = "SidebarHeaderComponent";
